##
## Small python text editor based on the:
## Very simple VT100 terminal text editor widget
## Copyright (c) 2015 Paul Sokolovsky
## Distributed under MIT License
## some code mangling by Robert Hammelrath, 2015, making it quite a little bit larger:
## - Ported the code to pyboard (still runs on Linux Python3 and on Linux Micropython)
##   It uses VCP_USB on Pyboard, but that may easyly be changed to UART
## - changed read keyboard function to comply with char-by-char input (on serial lines)
## - added support for TAB, BACKTAB, SAVE, DEL at end joining lines, Find,
## - Goto Line, Yank (delete line into buffer), Zap (insert buffer)
## - moved main into a function with some optional parameters
## - Added a status line and single line prompts for Quit, Save, Find and Goto
## - Added mouse support for pointing and scrolling
##
import sys
import gc
import _io
##
#ifdef LINUX
if sys.platform in ("linux", "darwin"):
    import os
#endif
#ifdef PYBOARD
if sys.platform == "pyboard":
    import pyb
#endif
#ifdef DEFINES
#define KEY_UP          0x05
#define KEY_DOWN        0x0b
#define KEY_LEFT        0x0c
#define KEY_RIGHT       0x0f
#define KEY_HOME        0x10
#define KEY_END         0x11
#define KEY_PGUP        0x17
#define KEY_PGDN        0x19
#define KEY_QUIT        0x03
#define KEY_ENTER       0x0a
#define KEY_BACKSPACE   0x08
#define KEY_DELETE      0x1f
#define KEY_WRITE       0x13
#define KEY_TAB         0x09
#define KEY_BACKTAB     0x15
#define KEY_FIND        0x06
#define KEY_GOTO        0x07
#define KEY_FIRST       0x02
#define KEY_LAST        0x14
#define KEY_FIND_AGAIN  0x0e
#define KEY_YANK        0x18
#define KEY_ZAP         0x16
#define KEY_TOGGLE      0x01
#define KEY_REPLC       0x12
#define KEY_DUP         0x04
#define KEY_MOUSE       0x1b
#define KEY_SCRLUP      0x1c
#define KEY_SCRLDN      0x1d
#else
KEY_UP        = 0x05
KEY_DOWN      = 0x0b
KEY_LEFT      = 0x0c
KEY_RIGHT     = 0x0f
KEY_HOME      = 0x10
KEY_END       = 0x11
KEY_PGUP      = 0x17
KEY_PGDN      = 0x19
KEY_QUIT      = 0x03
KEY_ENTER     = 0x0a
KEY_BACKSPACE = 0x08
KEY_DELETE    = 0x1f
KEY_WRITE     = 0x13
KEY_TAB       = 0x09
KEY_FIND      = 0x06
KEY_GOTO      = 0x07
KEY_MOUSE     = 0x1b
KEY_SCRLUP    = 0x1c
KEY_SCRLDN    = 0x1d
KEY_FIND_AGAIN= 0x0e
#ifndef BASIC
KEY_FIRST     = 0x02
KEY_LAST      = 0x14
KEY_YANK      = 0x18
KEY_ZAP       = 0x16
KEY_BACKTAB   = 0x15
KEY_TOGGLE    = 0x01
KEY_REPLC     = 0x12
KEY_DUP       = 0x04
#endif
#endif

class Editor:

    KEYMAP = { ## Gets lengthy
    b"\x1b[A" : KEY_UP,
    b"\x1b[B" : KEY_DOWN,
    b"\x1b[D" : KEY_LEFT,
    b"\x1b[C" : KEY_RIGHT,
    b"\x1b[H" : KEY_HOME, ## in Linux Terminal
    b"\x1bOH" : KEY_HOME, ## Picocom, Minicom
    b"\x1b[1~": KEY_HOME, ## Putty
    b"\x1b[F" : KEY_END,  ## Linux Terminal
    b"\x1bOF" : KEY_END,  ## Picocom, Minicom
    b"\x1b[4~": KEY_END,  ## Putty
    b"\x1b[5~": KEY_PGUP,
    b"\x1b[6~": KEY_PGDN,
    b"\x11"   : KEY_QUIT, ## Ctrl-Q
    b"\x03"   : KEY_QUIT, ## Ctrl-C as well
    b"\r"     : KEY_ENTER,
    b"\n"     : KEY_ENTER,
    b"\x7f"   : KEY_BACKSPACE, ## Ctrl-? (127)
    b"\x08"   : KEY_BACKSPACE,
    b"\x1b[3~": KEY_DELETE,
    b"\x13"   : KEY_WRITE,  ## Ctrl-S
    b"\x06"   : KEY_FIND, ## Ctrl-F
    b"\x0e"   : KEY_FIND_AGAIN, ## Ctrl-N
    b"\x07"   : KEY_GOTO, ##  Ctrl-G
    b"\x1b[M" : KEY_MOUSE,
#ifndef BASIC
    b"\x01"   : KEY_TOGGLE, ## Ctrl-A
    b"\x14"   : KEY_FIRST, ## Ctrl-T
    b"\x1b[1;5H": KEY_FIRST,
    b"\x02"   : KEY_LAST,  ## Ctrl-B
    b"\x1b[1;5F": KEY_LAST,
    b"\x1b[3;5~": KEY_YANK,
    b"\x18"   : KEY_YANK, ## Ctrl-X
    b"\x09"   : KEY_TAB,
    b"\x1b[Z" : KEY_BACKTAB, ## Shift Tab
    b"\x15"   : KEY_BACKTAB, ## Ctrl-U
    b"\x16"   : KEY_ZAP, ## Ctrl-V
    b"\x12"   : KEY_REPLC, ## Ctrl-R
    b"\x04"   : KEY_DUP, ## Ctrl-D
#endif
    }

    def __init__(self, tab_size, lnum):
        self.top_line = 0
        self.cur_line = 0
        self.row = 0
        self.col = 0
        if lnum:
            self.col_width = 5 ## width of line no. col
        else:
            self.col_width = 0
        self.col_fmt = "%4d "
        self.col_spc = "     "
        self.margin = 0
        self.scrolling = 0
        self.tab_size = tab_size
        self.changed = ' '
        self.message = ""
        self.find_pattern = ""
        self.replc_pattern = ""
        self.y_buffer = []
        self.content = [""]
        self.fname = None
        self.lastkey = 0
        self.autoindent = "y"
        self.case = "n"
#ifdef LINUX
    if sys.platform in ("linux", "darwin"):
        @staticmethod
        def wr(s):
            if isinstance(s, str):
                s = bytes(s, "utf-8")
            os.write(1, s)

        @staticmethod
        def rd():
           return os.read(0,1)
#endif
#ifdef PYBOARD
    if sys.platform == "pyboard":
        @staticmethod
        def wr(s):
            ns = 0
            while ns < len(s): # complicated but needed, since USB_VCP.write() has issues
                res = Editor.serialcomm.write(s[ns:])
                if res != None:
                    ns += res

        @staticmethod
        def rd():
            while not Editor.serialcomm.any():
                pass
            return Editor.serialcomm.read(1)
#endif
    @staticmethod
    def cls():
        Editor.wr(b"\x1b[2J")

    @staticmethod
    def goto(row, col):
        Editor.wr("\x1b[%d;%dH" % (row + 1, col + 1))

    @staticmethod
    def clear_to_eol():
        Editor.wr(b"\x1b[0K")

    @staticmethod
    def cursor(onoff):
        if onoff:
            Editor.wr(b"\x1b[?25h")
        else:
            Editor.wr(b"\x1b[?25l")

    @staticmethod
    def hilite(mode):
        if mode == 1:
            Editor.wr(b"\x1b[1m")
        elif mode == 2:
            Editor.wr(b"\x1b[2;7m")
        else:
            Editor.wr(b"\x1b[0m")

    def print_no(self, row, line):
        self.goto(row, 0)
        if self.col_width > 1:
            self.hilite(2)
            if line:
                self.wr(line)
            else:
                self.wr(self.col_spc)
            self.hilite(0)

    def get_input(self):  ## read from interface/keyboard one byte each and match against function keys
        while True:
            input = Editor.rd()
            if input == b'\x1b': ## starting with ESC, must be fct
                while True:
                    input += Editor.rd()
                    c = chr(input[-1])
                    if c == '~' or (c.isalpha() and c != 'O'):
                        break
            if input in self.KEYMAP:
                c = self.KEYMAP[input]
                if c == KEY_MOUSE: ## special for mice
                    mf = ord((Editor.rd())) & 0xe3 ## read 3 more chars
                    self.mouse_x = ord(Editor.rd()) - 33
                    self.mouse_y = ord(Editor.rd()) - 33
                    if mf == 0x61:
                        return KEY_SCRLDN
                    elif mf == 0x60:
                        return KEY_SCRLUP
                    else:
                        return KEY_MOUSE ## do nothing but set the cursor
                else:
                    return c
            elif input[0] >= 0x20: ## but only if no Ctrl-Char
                return input[0]
            else:
                self.message = repl(input)

    def display_window(self): ## Update window and status line
## Force cur_line and col to be in the reasonable limits
        self.cur_line = min(self.total_lines - 1, max(self.cur_line, 0))
        self.col = max(0, min(self.col, len(self.content[self.cur_line])))
## Check if Column is out of view, and align margin if needed
        if self.col >= self.width + self.margin:
            self.margin = self.col - self.width + int(self.width / 4)
        elif self.col < self.margin:
            self.margin = max(self.col - int(self.width / 4), 0)
## if cur_line is out of view, align top_line to given row
        if not (self.top_line <= self.cur_line < self.top_line + self.height): # Visible?
            self.top_line = max(self.cur_line - self.row, 0)
        self.row = self.cur_line - self.top_line
## update_screen
        self.cursor(False)
#ifndef BASIC
        if self.scrolling < 0:  ## scroll down by n lines
            self.scrbuf[-self.scrolling:] = self.scrbuf[:self.scrolling]
            self.scrbuf[:-self.scrolling] = ['\x01'] * -self.scrolling
            self.goto(0, 0)
            self.wr("\x1bM" * -self.scrolling)
        elif self.scrolling  > 0:  ## scroll up by n lines
            self.scrbuf[:-self.scrolling] = self.scrbuf[self.scrolling:]
            self.scrbuf[-self.scrolling:] = ['\x01'] * self.scrolling
            self.goto(self.height - 1, 0)
            self.wr("\x1bD " * self.scrolling)
        self.scrolling = 0
#endif
        i = self.top_line
        for c in range(self.height):
            if i == self.total_lines: ## at empty bottom screen part
                if self.scrbuf[c] != '\x04':
                    self.print_no(c, None)
                    self.clear_to_eol()
                    self.scrbuf[c] = '\x04'
            else:
                l = self.content[i][self.margin:self.margin + self.width]
                lnum = self.col_fmt % (i + 1)
                if (lnum + l) != self.scrbuf[c]: ## line changed, print it
                    self.print_no(c, lnum) ## print line no
                    self.wr(l)
                    if len(l) < self.width:
                        self.clear_to_eol()
                    self.scrbuf[c] = lnum + l
                i += 1
## display Status-Line
        if self.status == "y" or self.message:
            self.goto(self.height, 0)
            self.clear_to_eol() ## moved up for mate/xfce4-terminal
            self.hilite(1)
            if self.col_width > 0:
                self.wr(self.col_fmt % self.total_lines)
            self.wr("%c Ln: %d Col: %d  %s" % (self.changed, self.cur_line + 1, self.col + 1, self.message))
            self.hilite(0)
        self.cursor(True)
        self.goto(self.row, self.col - self.margin + self.col_width)

    def clear_status(self):
        if (self.status != "y") and self.message:
            self.goto(self.height, 0)
            self.clear_to_eol()
        self.message = ''

    def spaces(self, line, pos = 0): ## count spaces
        if pos: ## left to the cursor
            return len(line[:pos]) - len(line[:pos].rstrip(" "))
        else: ## at line start
            return len(line) - len(line.lstrip(" "))

    def line_edit(self, prompt, default):  ## simple one: only 3 fcts
        self.goto(self.height, 0)
        self.hilite(1)
        self.wr(prompt)
        self.wr(default)
        self.clear_to_eol()
        res = default
        self.message = ' ' # Shows status after lineedit
        while True:
            key = self.get_input()  ## Get Char of Fct.
            if key in (KEY_ENTER, KEY_TAB): ## Finis
                self.hilite(0)
                return res
            elif key == KEY_QUIT: ## Abort
                self.hilite(0)
                return None
            elif key in (KEY_BACKSPACE, KEY_DELETE): ## Backspace
                if (len(res) > 0):
                    res = res[:len(res)-1]
                    self.wr('\b \b')
            elif key >= 0x20: ## char to be added at the end
                if len(prompt) + len(res) < self.width - 1:
                    res += chr(key)
                    self.wr(chr(key))
            else:  ## ignore everything else
                pass

    def find_in_file(self, pattern, pos):
        self.find_pattern = pattern # remember it
        if self.case != "y":
            pattern = pattern.lower()
        spos = pos
        for line in range(self.cur_line, self.total_lines):
            if self.case == "y":
                match = self.content[line][spos:].find(pattern)
            else:
                match = self.content[line][spos:].lower().find(pattern)
            if match >= 0:
                break
            spos = 0
        else:
            self.message = pattern + " not found"
            return 0
        self.col = match + spos
        self.cur_line = line
        self.message = ' ' ## force status once
        return len(pattern)

    def handle_cursor_keys(self, key): ## keys which move, sanity checks later
        if key == KEY_DOWN:
            if self.cur_line < self.total_lines - 1:
                self.cur_line += 1
                if self.cur_line == self.top_line + self.height: self.scrolling = 1
        elif key == KEY_UP:
            if self.cur_line > 0:
                if self.cur_line == self.top_line: self.scrolling = -1
                self.cur_line -= 1
        elif key == KEY_LEFT:
            self.col -= 1
        elif key == KEY_RIGHT:
            self.col += 1
        elif key == KEY_HOME:
            ns = self.spaces(self.content[self.cur_line])
            if self.col > ns:
                self.col = ns
            else:
                self.col = 0
        elif key == KEY_END:
            self.col = len(self.content[self.cur_line])
        elif key == KEY_PGUP:
            self.cur_line -= self.height
        elif key == KEY_PGDN:
            self.cur_line += self.height
        elif key == KEY_FIND:
            pat = self.line_edit("Find: ", self.find_pattern)
            if pat:
                self.find_in_file(pat, self.col)
                self.row = int(self.height / 2)
        elif key == KEY_FIND_AGAIN:
            if self.find_pattern:
                self.find_in_file(self.find_pattern, self.col + 1)
                self.row = int(self.height / 2)
        elif key == KEY_GOTO: ## goto line
            line = self.line_edit("Goto Line: ", "")
            if line:
                try:
                    self.cur_line = int(line) - 1
                    self.row = int(self.height / 2)
                except:
                    pass
        elif key == KEY_MOUSE: ## Set Cursor
            if self.mouse_y < self.height:
                self.col = self.mouse_x + self.margin - self.col_width
                self.cur_line = self.mouse_y + self.top_line
        elif key == KEY_SCRLUP: ##
            if self.top_line > 0: 
                self.top_line = max(self.top_line - 3, 0)
                self.cur_line = min(self.cur_line, self.top_line + self.height - 1)
                self.scrolling = -3
        elif key == KEY_SCRLDN: ##
            if self.top_line + self.height < self.total_lines: 
                self.top_line = min(self.top_line + 3, self.total_lines - 1)
                self.cur_line = max(self.cur_line, self.top_line)
                self.scrolling = 3
#ifndef BASIC
        elif key == KEY_TOGGLE: ## Toggle Autoindent/Statusline/Search case
            pat = self.line_edit("Case Sensitive Search %c, Statusline %c, Autoindent %c: " % (self.case, self.status, self.autoindent), "")
            try:
                res =  [i.strip().lower() for i in pat.split(",")]
                if res[0]: self.case = res[0][0]
                if res[1]: self.status = res[1][0]
                if res[2]: self.autoindent = res[2][0]
            except:
                pass
        elif key == KEY_FIRST: ## first line
            self.cur_line = 0
        elif key == KEY_LAST: ## last line
            self.cur_line = self.total_lines - 1
            self.row = self.height - 1
            self.message = ' ' ## force status once
#endif
        else:
            return False
        return True

    def handle_edit_key(self, key): ## keys which change content
        l = self.content[self.cur_line]
        sc = self.changed
        self.changed = '*'
        if key == KEY_ENTER:
            self.content[self.cur_line] = l[:self.col]
            ni = 0
#ifndef BASIC
            if self.autoindent == "y": ## Autoindent
                ni = min(self.spaces(l, 0), self.col)  ## query indentation
                r = self.content[self.cur_line].partition("\x23")[0].rstrip() ## \x23 == #
                if r and r[-1] == ':' and self.col >= len(r): ## look for : as the last non-space before comment
                    ni += self.tab_size
#endif
            self.cur_line += 1
            self.content[self.cur_line:self.cur_line] = [' ' * ni + l[self.col:]]
            self.total_lines += 1
            self.col = ni
        elif key == KEY_BACKSPACE:
            if self.col > 0:
                self.content[self.cur_line] = l[:self.col - 1] + l[self.col:]
                self.col -= 1
#ifndef BASIC
            elif self.cur_line: # at the start of a line, but not the first
                self.col = len(self.content[self.cur_line - 1])
                self.content[self.cur_line - 1] += l
                del self.content[self.cur_line]
                self.cur_line -= 1
                self.total_lines -= 1
#endif
            else:
                self.changed = sc
        elif key == KEY_DELETE:
            if self.col < len(l):
                l = l[:self.col] + l[self.col + 1:]
                self.content[self.cur_line] = l
            elif (self.cur_line + 1) < self.total_lines: ## test for last line
                ni = 0
#ifndef BASIC
                if self.autoindent == "y": ## Autoindent reversed
                    ni = self.spaces(self.content[self.cur_line + 1])
#endif
                self.content[self.cur_line] = l + self.content.pop(self.cur_line + 1)[ni:]
                self.total_lines -= 1
            else:
                self.changed = sc
#ifndef BASIC
        elif key == KEY_TAB: ## TABify line
            ns = self.spaces(l, 0)
            if ns and self.col < ns: # at BOL
                ni = self.tab_size - ns % self.tab_size
            else:
                ni = self.tab_size - self.col % self.tab_size
            self.content[self.cur_line] = l[:self.col] + ' ' * ni + l[self.col:]
            if ns == len(l) or self.col >= ns: # lines of spaces or in text
                self.col += ni # move cursor
        elif key == KEY_BACKTAB: ## unTABify line
            ns = self.spaces(l, 0)
            if ns and self.col < ns: # at BOL
                ni = (ns - 1) % self.tab_size + 1
                self.content[self.cur_line] = l[ni:]
            else: # left to cursor & move
                ns = self.spaces(l, self.col)
                ni = (self.col - 1) % self.tab_size + 1
                if (ns >= ni):
                    self.content[self.cur_line] = l[:self.col - ni] + l[self.col:]
                    self.col -= ni
                else:
                    self.changed = sc
        elif key == KEY_YANK:  # delete line into buffer
            if key == self.lastkey: # yank series?
                self.y_buffer.append(l) # add line
            else:
                del self.y_buffer # set line
                self.y_buffer = [l]
            if self.total_lines > 1: ## not a single line
                del self.content[self.cur_line]
                self.total_lines -= 1
                if self.cur_line  >= self.total_lines: ## on last line move pointer
                    self.cur_line -= 1
            else: ## line is kept but wiped
                self.content[self.cur_line] = ''
        elif key == KEY_DUP:  # copy line into buffer and go down one line
            if key == self.lastkey: # dup series?
                self.y_buffer.append(l) # add line
            else:
                del self.y_buffer # set line
                self.y_buffer = [l]
            if self.cur_line + 1 < self.total_lines:
                self.cur_line += 1
            self.changed = sc
        elif key == KEY_ZAP: ## insert buffer
            if self.y_buffer:
                self.content[self.cur_line:self.cur_line] = self.y_buffer # insert lines
                self.total_lines += len(self.y_buffer)
            else:
                self.changed = sc
        elif key == KEY_REPLC:
            count = 0
            self.changed = sc
            pat = self.line_edit("Find: ", self.find_pattern)
            if pat:
                rpat = self.line_edit("Replace with: ", self.replc_pattern)
                if rpat != None:
                    self.replc_pattern = rpat
                    q = ''
                    while True:
                        ni = self.find_in_file(pat, self.col)
                        if ni:
                            if q != 'a':
                                self.message = "Replace (yes/No/all/quit) ? "
                                self.display_window()
                                key = self.get_input()  ## Get Char of Fct.
                                q = chr(key).lower()
                            if q == 'q' or key == KEY_QUIT:
                                break
                            elif q in ('a','y'):
                                self.content[self.cur_line] = self.content[self.cur_line][:self.col] + rpat + self.content[self.cur_line][self.col + ni:]
                                self.col += len(rpat)
                                count += 1
                                self.changed = '*'
                            else: ## everything else is no
                                self.col += 1
                        else:
                            break
                    if count:
                        self.message = "'%s' replaced %d times" % (pat, count)
#endif
        elif key == KEY_WRITE:
            fname = self.fname
            if fname == None:
                fname = ""
            fname = self.line_edit("File Name: ", fname)
            if fname:
                try:
                    with open(fname, "w") as f:
                        for l in self.content:
                            f.write(l + '\n')
                    self.changed = " "
                    self.fname = fname
                except:
                    pass
            else:
                self.changed = sc
        elif key >= 0x20:
            self.content[self.cur_line] = l[:self.col] + chr(key) + l[self.col:]
            self.col += 1
        else: # Ctrl key or not supported function, ignore
            self.changed = sc

    def edit_loop(self): ## main editing loop
        self.scrbuf = [""] * self.height
        self.total_lines = len(self.content)
        ## strip trailing whitespace and expand tabs
        for i in range(self.total_lines):
            self.content[i] = self.expandtabs(self.content[i].rstrip('\r\n\t '))

        while True:
            self.display_window()  ## Update & display window
            key = self.get_input()  ## Get Char of Fct-key code
            self.clear_status() ## From messages

            if key == KEY_QUIT:
                if self.changed != ' ' and self.fname != None:
                    res = self.line_edit("Content changed! Quit without saving (y/N)? ", "N")
                    if not res or res[0].upper() != 'Y':
                        continue
                return None
            elif  self.handle_cursor_keys(key):
                pass
            else: self.handle_edit_key(key)
            self.lastkey = key

    def init_tty(self, device, baud):
#ifdef PYBOARD
        if sys.platform == "pyboard":
            if (device):
                Editor.serialcomm = pyb.UART(device, baud)
                self.status = "n"

            else:
                Editor.serialcomm = pyb.USB_VCP()
                Editor.serialcomm.setinterrupt(-1)
                self.status = "y"
            Editor.sdev = device
#endif
#ifdef LINUX
        if sys.platform in ("linux", "darwin"):
            import tty, termios
            self.org_termios = termios.tcgetattr(0)
            tty.setraw(0)
            self.status = "y"
#endif
        ## Set cursor far off and ask for reporting its position = size of the window.
        self.wr('\x1b[999;999H\x1b[6n')
        pos = b''
        char = self.rd() ## expect ESC[yyy;xxxR
        while char != b'R':
            pos += char
            char = self.rd()
        (self.height, self.width) = [int(i, 10) for i in pos[2:].split(b';')]
        self.height -= 1
        self.width -= self.col_width
        self.wr('\x1b[?9h') ## enable mouse reporting
        self.wr('\x1b[1;%dr' % self.height) ## enable partial scrolling, Buggy?

    def deinit_tty(self):
        ## Do not leave cursor in the middle of screen
        self.wr('\x1b[?9l\x1b[r') ## disable mouse reporting, enable scrolling
        self.goto(self.height, 0)
        self.clear_to_eol()
#ifdef PYBOARD
        if sys.platform == "pyboard" and not Editor.sdev:
            Editor.serialcomm.setinterrupt(3)
#endif
#ifdef LINUX
        if sys.platform in ("linux", "darwin"):
            import termios
            termios.tcsetattr(0, termios.TCSANOW, self.org_termios)
#endif
## expandtabs: hopefully sometimes replaced by the built-in function
    def expandtabs(self, s):
        if '\t' in s:
            sb = _io.StringIO()
            pos = 0
            for c in s:
                if c == '\t': ## tab is seen
                    sb.write(" " * (8 - pos % 8)) ## replace by space
                    pos += 8 - pos % 8
                else:
                    sb.write(c)
                    pos += 1
            return sb.getvalue()
        else:
            return s

def pye(content = None, tab_size = 4, lnum = 1, device = 0, baud = 115200):
## prepare content
    e = Editor(tab_size, lnum)
    if type(content) == str: ## String = Filename
        e.fname = content
        if e.fname:  ## non-empty String -> read it
            try:
                with open(e.fname) as f:
                    e.content = f.readlines()
                if not e.content: ## empty file
                    e.content = [""]
            except Exception as err:
                print ('Could not load %s, Reason: "%s"' % (e.fname, err))
                del e
                return
    elif type(content) == list and len(content) > 0 and type(content[0]) == str:
        ## non-empty list of strings -> edit
        e.content = content
## edit
    e.init_tty(device, baud)
    e.edit_loop()
    e.deinit_tty()
## clean-up
    if e.fname == None:
        content = e.content
    else:
        content = e.fname
    del e
    gc.collect()
    return content

#ifdef LINUX
if __name__ == "__main__":
    if sys.platform in ("linux", "darwin"):
        import getopt
        args_dict = {'-t' : '4', '-l' : "None", '-h' : "None"}
        usage = ("Usage: python3 pye.py [-t tabsize] [-l] [filename]\n"
                 "         -t x set tabsize\n"
                 "         -l   suppress line number column")
        try:
            options, args = getopt.getopt(sys.argv[1:],"t:lh") ## get the options -t x -l -h
        except:
            print ("Undefined option in: " + ' '.join(sys.argv[1:]))
            print (usage)
            sys.exit()
        args_dict.update( options ) ## Sort the input into the default parameters
        if args_dict["-h"] != "None":
            print(usage)
            sys.exit()
        if len(args) > 0:
            name = args[0]
        else:
            name = ""
        try:
            tsize = int(args_dict["-t"])
        except:
            tsize = 4
        if args_dict["-l"] != "None":
            lnum = 0
        else:
            lnum = 1
        pye(name, tsize, lnum)
#endif

