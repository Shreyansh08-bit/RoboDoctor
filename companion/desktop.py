import argparse
import math
import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

from companion.client import BackendClient, WORKSPACE_URL
from companion.session import ShellSession

BG, PANEL, LINE, FG, MUTED, ACCENT = '#f5f7f9', '#eaf1f5', '#dce6eb', '#294e5b', '#6d8793', '#438995'


class CapsuleButton(tk.Canvas):
    def __init__(self,parent,text,command,bg=PANEL,fg=FG,state='normal',padx=12):
        self.caption=text; self.action=command; self.enabled=state!='disabled'; self.color=bg; self.ink=fg
        super().__init__(parent,width=max(62,len(text)*7+padx*2),height=34,bg=BG,highlightthickness=0,cursor='hand2')
        self.bind('<Button-1>',lambda event:self.action() if self.enabled else None)
        self.paint()
    def paint(self):
        self.delete('all'); width=int(self.cget('width'))
        color=self.color if self.enabled else '#e9eef1'
        self.create_line(17,17,width-17,17,fill=color,width=32,capstyle='round')
        self.create_text(width/2,17,text=self.caption,fill=self.ink if self.enabled else '#a5b4bc',font=('Segoe UI',9))
    def configure(self,**kwargs):
        if 'state' in kwargs: self.enabled=kwargs.pop('state')!='disabled'
        if kwargs: super().configure(**kwargs)
        self.paint()


class ManagedTerminal:
    def __init__(self, companion):
        self.companion = companion
        self.root = tk.Toplevel(companion.root)
        self.root.title('RoboDoctor Managed Session')
        self.root.geometry('810x490')
        self.root.configure(bg=BG)
        self.events = queue.Queue()
        self.client = BackendClient()
        self.session = ShellSession(companion.cwd)
        try:
            self.client.connect(os.path.basename(self.session.shell), self.session.cwd)
        except Exception:
            self.session.close()
            raise
        self.root.title(f'RoboDoctor · {self.client.name}')
        companion.terminals[self.client.session_id] = self
        self.last_focus_id = None
        self.running = False
        self.closed = False
        tk.Label(self.root, text=self.client.name, font=('Segoe UI', 13, 'bold'), bg=BG, fg=FG).pack(anchor='w', padx=19, pady=(16, 4))
        tk.Label(self.root, text='Only commands you type and run are executed. Suggestions never run automatically.', bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=19)
        self.root.minsize(640, 400)
        self.output = tk.Text(self.root, height=12, bg='#ffffff', fg='#3c6373', insertbackground=FG, font=('Consolas', 10), wrap='word', relief='flat', padx=13, pady=12)
        self.output.pack(fill='both', expand=True, padx=18, pady=15)
        self.output.configure(state='disabled')
        self.status = tk.Label(self.root, text=self.session.cwd, bg=BG, fg=MUTED, anchor='w', font=('Segoe UI', 9))
        self.status.pack(fill='x', padx=19)
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill='x', padx=18, pady=14)
        tk.Label(row, text='$', bg=BG, fg=ACCENT).pack(side='left', padx=(0, 8))
        self.command = tk.Entry(row, bg=PANEL, fg=FG, insertbackground=FG, font=('Consolas', 10), relief='flat')
        self.command.pack(side='left', fill='x', expand=True, ipady=7)
        self.command.bind('<Return>', self.run)
        self.run_button = CapsuleButton(row, text='Run', command=self.run, bg=ACCENT, fg=BG, padx=15)
        self.run_button.pack(side='left', padx=(10, 0))
        self.stop_button = CapsuleButton(row, text='Stop', command=self.stop, bg=PANEL, fg=FG, padx=12, state='disabled')
        self.stop_button.pack(side='left', padx=(7, 0))
        CapsuleButton(row, text='Inspect', command=lambda: companion.open_session(self.client.session_id), bg=PANEL, fg=FG, padx=12).pack(side='left', padx=(7, 0))
        self.command.focus_set()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.drain)
        threading.Thread(target=self.heartbeat, daemon=True).start()
        self.append('Persistent PowerShell session on Windows; Bash on Ubuntu.\nRun complete, non-interactive commands. Stop ends the running process tree.\n\n')

    def append(self, text):
        self.output.configure(state='normal')
        self.output.insert('end', text)
        if int(self.output.index('end-1c').split('.')[0]) > 800:
            self.output.delete('1.0', '200.0')
        self.output.see('end')
        self.output.configure(state='disabled')

    def heartbeat(self):
        while not self.closed:
            try:
                self.client.request('POST', '/terminal/heartbeat')
                state = self.client.request('GET', '/workspace')
                focus = state.get('focus_request')
                if focus and focus['session_id'] == self.client.session_id and focus['id'] != self.last_focus_id:
                    self.last_focus_id = focus['id']
                    self.events.put(('focus', None))
            except Exception:
                self.events.put(('connection', 'Backend disconnected. Close and reopen this terminal after restarting the backend.'))
            time.sleep(5)

    def run(self, event=None):
        if self.running:
            return
        command = self.command.get().strip()
        if not command:
            return
        if len(command) > 4096:
            self.status.configure(text='Command too long (maximum 4096 characters).')
            return
        self.command.delete(0, 'end')
        self.append('$ ' + command + '\n')
        self.running = True
        self.command.configure(state='disabled')
        self.run_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.status.configure(text='Running…')
        threading.Thread(target=self.execute, args=(command,), daemon=True).start()

    def execute(self, command):
        payload = {'sequence': self.session.sequence + 1, 'command': command, 'output': '',
                   'exit_code': None, 'state': 'running', 'cwd': self.session.cwd, 'environment': {}}
        try:
            # If capture cannot register, don't execute a command behind a disconnected status.
            self.client.request('POST', '/terminal/event', payload)
            last_capture = 0.0
            def output(line, recent):
                nonlocal last_capture
                self.events.put(('output', line))
                if time.monotonic() - last_capture > 1:
                    last_capture = time.monotonic()
                    try:
                        self.client.request('POST', '/terminal/event', {**payload, 'output': recent})
                    except Exception:
                        pass
            result = self.session.execute(command, output)
            self.client.request('POST', '/terminal/event', result)
            self.events.put(('done', f"Exit code: {result['exit_code']}  ·  {result['cwd']}"))
        except Exception as exc:
            self.events.put(('output', '\nCapture error: ' + str(exc) + '\n'))
            # Never leave a registered run appearing active after a local runner error.
            try:
                self.client.request('POST', '/terminal/event', {**payload, 'state': 'cancelled', 'exit_code': 1,
                                    'output': 'Managed session error: ' + str(exc)})
            except Exception:
                pass
            self.events.put(('done', 'Session error. Review the output before retrying.'))

    def drain(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'output':
                self.append(value)
            elif kind == 'focus':
                try:
                    self.root.deiconify(); self.root.lift(); self.root.focus_force()
                except tk.TclError:
                    self.status.configure(text='Open this terminal from your taskbar; the OS restricted focus.')
                def acknowledge():
                    try: self.client.request('POST','/terminal/focus-ack')
                    except Exception: pass
                threading.Thread(target=acknowledge, daemon=True).start()
            elif kind == 'done':
                self.running = False
                self.append('\n' + value + '\n\n')
                self.status.configure(text=value)
                self.command.configure(state='normal')
                self.run_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                self.command.focus_set()
            else:
                self.status.configure(text=value)
        self.root.after(100, self.drain)

    def stop(self):
        if self.running:
            self.status.configure(text='Stopping this command and its process tree…')
            threading.Thread(target=self.session.close, daemon=True).start()

    def close(self):
        self.closed = True
        self.session.close()
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.root.destroy()
        self.companion.terminals.pop(self.client.session_id, None)


class Companion:
    def __init__(self, cwd=None):
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.root = tk.Tk()
        self.root.title('RoboDoctor Companion')
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=BG)
        # Leave the Windows notification/calendar corner clear.
        self.root.geometry(f'132x150+48+{self.root.winfo_screenheight()-220}')
        self.root.configure(bg='white')
        if os.name == 'nt':
            self.root.attributes('-transparentcolor', 'white')
        self.robot = tk.PhotoImage(file=str(Path(__file__).resolve().parents[1] / 'assets' / 'robot.png')).subsample(5,5)
        self.root.iconphoto(True,self.robot)
        self.canvas = tk.Canvas(self.root, width=132, height=150, bg='white', highlightthickness=0)
        self.canvas.pack()
        self.client = BackendClient()
        self.events = queue.Queue()
        self.terminals = {}
        self.issue_count = 0
        self.last_focus_id = None
        self.closed = False
        self.busy = False
        self.visual_state = 'sleeping'
        self.visual_phase = 0.0
        self.warning_frames = 0
        self.draw('sleeping')
        self.menu = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=FG, activebackground='#dfeef3')
        self.menu.add_command(label='Open workspace', command=self.open_workspace)
        self.menu.add_command(label='New managed terminal', command=self.open_terminal)
        self.menu.add_separator()
        self.menu.add_command(label='Quit companion', command=self.close)
        self.canvas.bind('<Double-Button-1>', self.open_workspace)
        self.canvas.bind('<ButtonPress-1>', self.drag_start)
        self.canvas.bind('<B1-Motion>', self.drag_move)
        self.canvas.bind('<Button-3>', lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.root.bind('<Return>', self.open_workspace)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.drain)
        self.root.after(160, self.animate)
        if os.name == 'nt':
            self.root.after(100, self.register_windows_launcher)
        threading.Thread(target=self.poll, daemon=True).start()

    def register_windows_launcher(self):
        # Tk's borderless windows default to tool-window styles. Register this visible
        # launcher as an application window so Windows task switching/accessibility
        # tools can discover it while preserving the compact borderless surface.
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        hwnd = user32.GetParent(self.root.winfo_id())
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, (style & ~(0x80 | 0x08000000)) | 0x40000)
        style = user32.GetWindowLongW(hwnd, -16)
        user32.SetWindowLongW(hwnd, -16, style & ~0x00C40000)  # No title bar or resize frame.
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos(hwnd, None, 0, 0, 132, 150, 0x36)  # Recalculate frame at launcher size.
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow(hwnd, 4)  # Show without stealing focus from the user's editor.

    def draw(self, label):
        self.visual_state = label
        c = self.canvas
        c.delete('all')
        c.create_image(66, 61, image=self.robot)
        # Expression overlays sit inside the supplied face; body/proportions stay intact.
        face = '#ffd531'
        if label in {'sleeping','worried','investigating','unresolved'}:
            for x in (49,74):
                c.create_oval(x-5,42,x+5,51,fill=face,outline=face)
                if label == 'sleeping':
                    c.create_arc(x-4,42,x+4,49,start=180,extent=180,style='arc',outline='#215762',width=2)
                elif label == 'investigating':
                    c.create_oval(x-1,44,x+4,49,fill='#215762',outline='')
                else:
                    c.create_oval(x-3,44,x+3,50,fill='#215762',outline='')
                    c.create_line(x-4,41,x+4,39 if x<60 else 43,fill='#215762',width=2)
            if label in {'worried','unresolved'}:
                c.create_oval(57,49,68,56,fill=face,outline=face)
                c.create_arc(58,52,66,60,start=20,extent=140,style='arc',outline='#215762',width=2)
        labels={'sleeping':'Resting','healthy':'Looks good','worried':f'{self.issue_count} issue' + ('s' if self.issue_count!=1 else ''),
            'investigating':'Analyzing…','ready':'Diagnosis ready','unresolved':'Needs more evidence','offline':'Backend offline','listening':'Listening'}
        if self.issue_count > 1 and label == 'ready':
            labels['ready'] = f'{self.issue_count} issues / ready'
        color = '#916e2f' if label in {'worried','unresolved'} else '#477a89'
        # Rounded status pill, no enclosing desktop box.
        c.create_line(19,137,113,137,fill='#edf4f6',width=22,capstyle='round')
        c.create_text(66,137,text=labels.get(label,label),fill=color,font=('Segoe UI',8))

    def animate(self):
        if self.closed: return
        # A blink every nine seconds; only investigating has gentle purposeful movement.
        self.visual_phase += 1
        if self.visual_state == 'investigating':
            self.canvas.delete('thinking-dot')
            x = 58 + (int(self.visual_phase)%3)*7
            self.canvas.create_oval(x,122,x+3,125,fill=ACCENT,outline='',tags='thinking-dot')
        elif int(self.visual_phase)%45 == 0 and self.visual_state in {'healthy','ready'}:
            for x in (49,74):
                self.canvas.create_line(x-4,46,x+4,46,fill='#ffd531',width=8,tags='blink')
            self.root.after(160,lambda:self.canvas.delete('blink'))
        self.root.after(200,self.animate)

    def drag_start(self, event):
        self.drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag_move(self, event):
        x, y, before_x, before_y = self.drag
        self.root.geometry(f'+{max(0, before_x + event.x_root-x)}+{max(0, before_y + event.y_root-y)}')

    def poll(self):
        while not self.closed:
            try:
                data = self.client.request('GET', '/workspace')
                self.issue_count = data.get('issue_count',0)
                label = data.get('emotion','sleeping')
                if any((session.get('execution') or {}).get('state')=='running' for session in data.get('sessions',[])) and not self.issue_count and not data['analyzing']:
                    label='listening'
                self.events.put(('state',label))
            except Exception:
                self.events.put(('state','offline'))
            time.sleep(2)

    def open_session(self, sid):
        def route():
            try:
                state=self.client.request('POST',f'/sessions/{sid}/select')
                issue=next((i for i in state['issues'] if i['session_id']==sid),None)
                webbrowser.open(WORKSPACE_URL.split('?')[0] + f'?session={sid}',new=0,autoraise=True)
                if issue: self.client.request('POST',f"/issues/{issue['id']}/open",timeout=360)
            except Exception as exc: self.events.put(('error',str(exc)))
        threading.Thread(target=route,daemon=True).start()

    def open_workspace(self, event=None):
        if self.busy: return
        self.busy=True
        def route():
            try:
                state=self.client.request('GET','/workspace')
                issues=state['issues']
                # Multiple issues stay unopened until the user chooses one.
                if len(issues)==1:
                    sid=issues[0]['session_id']
                    self.client.request('POST',f'/sessions/{sid}/select')
                    webbrowser.open(WORKSPACE_URL.split('?')[0]+f'?session={sid}',new=0,autoraise=True)
                    self.client.request('POST',f"/issues/{issues[0]['id']}/open",timeout=360)
                else:
                    webbrowser.open(WORKSPACE_URL,new=0,autoraise=True)
            except Exception as exc: self.events.put(('error',str(exc)))
            finally: self.events.put(('finished',None))
        threading.Thread(target=route,daemon=True).start()

    def open_terminal(self):
        try: ManagedTerminal(self)
        except Exception as exc: messagebox.showerror('RoboDoctor terminal',str(exc),parent=self.root)

    def drain(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'state' and not self.busy:
                self.draw(value)
            elif kind == 'finished':
                self.busy = False
            elif kind == 'error':
                # The web workspace exposes setup/busy states; no intrusive popup on diagnosis.
                self.draw('offline' if 'connect' in value.lower() else 'unresolved')
        self.root.after(100, self.drain)

    def close(self):
        self.closed = True
        for terminal in list(self.terminals.values()):
            terminal.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='RoboDoctor quiet desktop launcher')
    parser.add_argument('--cwd', help='Initial managed terminal working directory')
    parser.add_argument('--terminal', action='store_true', help='Also open the managed terminal')
    args = parser.parse_args()
    companion = Companion(args.cwd)
    if args.terminal:
        companion.root.after(300, companion.open_terminal)
    import signal
    signal.signal(signal.SIGTERM, lambda *_: companion.close())
    try:
        companion.root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        if not companion.closed:
            companion.close()


if __name__ == '__main__':
    main()
