import argparse
import math
import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox

from companion.client import BackendClient, WORKSPACE_URL
from companion.session import ShellSession

BG, PANEL, LINE, FG, MUTED, ACCENT = '#111619', '#192125', '#344047', '#dce5e3', '#8c9a9c', '#96c6af'


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
        self.running = False
        self.closed = False
        tk.Label(self.root, text='RoboDoctor terminal', font=('Segoe UI', 13, 'bold'), bg=BG, fg=FG).pack(anchor='w', padx=19, pady=(16, 4))
        tk.Label(self.root, text='Only commands you type and run are executed. Suggestions never run automatically.', bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=19)
        self.output = tk.Text(self.root, bg='#0e1417', fg='#b8cac0', insertbackground=FG, font=('Consolas', 10), wrap='word', relief='flat', padx=13, pady=12)
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
        self.run_button = tk.Button(row, text='Run', command=self.run, bg=ACCENT, fg=BG, relief='flat', padx=15)
        self.run_button.pack(side='left', padx=(10, 0))
        self.stop_button = tk.Button(row, text='Stop', command=self.stop, bg=PANEL, fg=FG, relief='flat', padx=12, state='disabled')
        self.stop_button.pack(side='left', padx=(7, 0))
        tk.Button(row, text='Inspect', command=companion.open_workspace, bg=PANEL, fg=FG, relief='flat', padx=12).pack(side='left', padx=(7, 0))
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
        self.companion.terminal = None


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
        self.root.geometry(f'76x82+48+{self.root.winfo_screenheight()-154}')
        self.canvas = tk.Canvas(self.root, width=76, height=82, bg=BG, highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack()
        self.client = BackendClient()
        self.events = queue.Queue()
        self.terminal = None
        self.closed = False
        self.busy = False
        self.visual_state = 'sleeping'
        self.visual_phase = 0.0
        self.warning_frames = 0
        self.draw('sleeping')
        self.menu = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=FG, activebackground='#293b32')
        self.menu.add_command(label='Open workspace', command=self.open_workspace)
        self.menu.add_command(label='Open managed terminal', command=self.open_terminal)
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
        user32.SetWindowPos(hwnd, None, 0, 0, 76, 82, 0x36)  # Recalculate frame at launcher size.
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow(hwnd, 4)  # Show without stealing focus from the user's editor.

    def draw(self, label):
        if label == 'check' and self.visual_state != 'check':
            self.warning_frames = 12
        self.visual_state = label
        c = self.canvas
        c.delete('all')
        color = '#d3b277' if label == 'check' else ACCENT
        c.create_line(38, 18, 38, 23, fill=color)
        c.create_oval(36, 15, 40, 19, fill=color, outline='')
        c.create_rectangle(21, 24, 55, 49, outline='#668275', width=1, fill='#1c2b24')
        c.create_rectangle(25, 29, 51, 40, fill='#101b16', outline='')
        for x in [31, 44]:
            c.create_line(x-3, 35, x+3, 35, fill=color, width=2, tags='eyes')
        c.create_line(34, 44, 42, 44, fill='#6d8c7a')
        c.create_text(61, 21, text='z' if label == 'sleeping' else '·', fill=MUTED, font=('Segoe UI', 9))
        c.create_text(38, 65, text=label, fill=MUTED, font=('Segoe UI', 8))

    def animate(self):
        # Only the eyes change gently; no position/size changes or flashing.
        if self.closed:
            return
        self.visual_phase += 0.14
        base = '#d3b277' if self.visual_state == 'check' else ACCENT
        brightness = 0.9 + 0.1 * (math.sin(self.visual_phase) + 1) / 2
        if self.warning_frames:
            self.warning_frames -= 1
            brightness = 0.9 + 0.1 * math.sin(math.pi * self.warning_frames / 12)
        self.canvas.itemconfigure('eyes', fill='#' + ''.join(f'{int(int(base[i:i+2],16)*brightness):02x}' for i in (1,3,5)))
        self.root.after(160, self.animate)

    def drag_start(self, event):
        self.drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag_move(self, event):
        x, y, before_x, before_y = self.drag
        self.root.geometry(f'+{max(0, before_x + event.x_root-x)}+{max(0, before_y + event.y_root-y)}')

    def poll(self):
        while not self.closed:
            try:
                data = self.client.request('GET', '/workspace')
                latest = data.get('latest')
                running = (data['terminal'].get('execution') or {}).get('state') == 'running'
                label = 'checking' if data['analyzing'] else 'listening' if running else ('check' if latest and latest['status'] == 'problem' else 'sleeping')
                self.events.put(('state', label))
            except Exception:
                self.events.put(('state', 'offline'))
            time.sleep(3)

    def open_workspace(self, event=None):
        if self.busy:
            return
        self.busy = True
        self.draw('checking')
        def inspect():
            try:
                # Browser launching must not block Tk's event loop.
                if not webbrowser.open(WORKSPACE_URL, new=0, autoraise=True):
                    self.events.put(('error', 'Open http://127.0.0.1:5173 in your browser.'))
                snapshot = self.client.request('GET', '/workspace')
                execution = snapshot['terminal']['execution']
                if execution and execution['state'] != 'running':
                    self.client.request('POST', '/terminal/diagnose', timeout=210)
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('finished', None))
        threading.Thread(target=inspect, daemon=True).start()

    def open_terminal(self):
        if self.terminal:
            self.terminal.root.deiconify()
            self.terminal.root.lift()
            return
        try:
            self.terminal = ManagedTerminal(self)
        except Exception as exc:
            for child in self.root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
            messagebox.showerror('RoboDoctor terminal', str(exc), parent=self.root)

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
                self.draw('offline' if 'connect' in value.lower() else 'check')
        self.root.after(100, self.drain)

    def close(self):
        self.closed = True
        if self.terminal:
            self.terminal.close()
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
