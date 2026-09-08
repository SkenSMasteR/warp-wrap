#!/usr/bin/env python3

import curses
import subprocess
import threading
import time
import math

LOGO = r"""
 ▄█     █▄     ▄████████    ▄████████    ▄███████▄                 ▄█     █▄     ▄████████    ▄████████    ▄███████▄ 
███     ███   ███    ███   ███    ███   ███    ███                ███     ███   ███    ███   ███    ███   ███    ███ 
███     ███   ███    ███   ███    ███   ███    ███                ███     ███   ███    ███   ███    ███   ███    ███ 
███     ███   ███    ███  ▄███▄▄▄▄██▀   ███    ███  ▄▄▄▄▄▄▄▄▄▄▄   ███     ███  ▄███▄▄▄▄██▀   ███    ███   ███    ███ 
███     ███ ▀███████████ ▀▀███▀▀▀▀▀   ▀█████████▀  ▐░░░░░░░░░░░▌  ███     ███ ▀▀███▀▀▀▀▀   ▀███████████ ▀█████████▀  
███     ███   ███    ███ ▀███████████   ███         ▀▀▀▀▀▀▀▀▀▀▀   ███     ███ ▀███████████   ███    ███   ███        
███ ▄█▄ ███   ███    ███   ███    ███   ███                       ███ ▄█▄ ███  ███    ███    ███    ███   ███        
 ▀███▀███▀    ███    █▀    ███    ███  ▄████▀                      ▀███▀███▀   ███    ███    ███    █▀   ▄████▀      
                           ███    ███                                          ███    ███                           
""".strip("\n").splitlines()
LOGO = [line for line in LOGO if line.strip() != ""] or LOGO


class WarpWrapper:
    def __init__(self, update_interval=1.0):
        self.status = "Unknown"
        self.raw_output = ""
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.update_interval = update_interval
        self.ip = "Unknown"
        self._ip_fetch_every = 5
        self.confirming = False
        self.connected_confirmed = True
        self.pre_connect_ip = None
        self.disconnecting = False
        self.disconnected_confirmed = True
        self.pre_disconnect_ip = None

    def _run(self, cmd):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except Exception as e:
            return "", str(e), -1

    def _update_status(self):
        stdout, stderr, rc = self._run(["warp-cli", "status"])
        with self.lock:
            if rc == 0:
                self.raw_output = stdout
                for line in stdout.splitlines():
                    if line.startswith("Status update:"):
                        self.status = line.split(":", 1)[1].strip()
                        break
                else:
                    self.status = stdout if stdout else "No status"
            else:
                self.status = f"Error: {stderr or 'warp-cli not found?'}"
                self.raw_output = stderr

    def _update_ip(self):
        stdout, stderr, rc = self._run(["curl", "-4", "-s", "--max-time", "3", "https://ifconfig.me"])
        with self.lock:
            self.ip = stdout.strip() if rc == 0 and stdout else "Unknown"

    def _status_loop(self):
        tick = 0
        while self.running:
            self._update_status()

            with self.lock:
                confirming = self.confirming
                disconnecting = self.disconnecting

            if confirming:
                self._update_ip()
                with self.lock:
                    if "Disconnected" in self.status:
                        self.confirming = False
                    elif ("Connected" in self.status and self.ip != "Unknown"
                          and self.ip != self.pre_connect_ip):
                        self.confirming = False
                        self.connected_confirmed = True
            elif disconnecting:
                self._update_ip()
                with self.lock:
                    if ("Disconnected" in self.status and self.ip != "Unknown"
                            and self.ip != self.pre_disconnect_ip):
                        self.disconnecting = False
                        self.disconnected_confirmed = True
            elif tick % self._ip_fetch_every == 0:
                self._update_ip()

            tick += 1
            time.sleep(self.update_interval)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._status_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def connect(self):
        with self.lock:
            self.pre_connect_ip = self.ip
            self.confirming = True
            self.connected_confirmed = False
            self.disconnecting = False
        stdout, stderr, rc = self._run(["warp-cli", "connect"])
        return rc == 0 and "Success" in stdout

    def disconnect(self):
        with self.lock:
            self.pre_disconnect_ip = self.ip
            self.disconnecting = True
            self.disconnected_confirmed = False
            self.confirming = False
        stdout, stderr, rc = self._run(["warp-cli", "disconnect"])
        return rc == 0 and "Success" in stdout


def draw_circle(stdscr, center_y, center_x, radius, status_text,
                outline_color=0, text_color=0,
                spin_angle=None, spin_width=50,
                highlight_color=0, base_color=0):
    height, width = stdscr.getmaxyx()
    aspect = 2.2
    tolerance = 0.4

    for dy in range(-radius, radius + 1):
        y = center_y + dy
        if y < 0 or y >= height:
            continue
        max_dx = int(radius * aspect) + 1
        for dx in range(-max_dx, max_dx + 1):
            x = center_x + dx
            if x < 0 or x >= width:
                continue
            x_norm = dx / aspect
            dist = math.hypot(x_norm, dy)
            if radius - tolerance <= dist <= radius + tolerance:
                if spin_angle is not None:
                    angle = math.degrees(math.atan2(dy, x_norm)) % 360
                    diff = abs(angle - spin_angle) % 360
                    diff = min(diff, 360 - diff)
                    color = highlight_color if diff <= spin_width / 2 else base_color
                else:
                    color = outline_color
                try:
                    if color:
                        stdscr.addch(y, x, '█', color)
                    else:
                        stdscr.addch(y, x, '█')
                except curses.error:
                    pass

    text = f" {status_text} "
    x_start = center_x - len(text) // 2
    y_start = center_y
    if 0 <= y_start < height and 0 <= x_start < width:
        try:
            for i in range(len(text)):
                if 0 <= x_start + i < width:
                    stdscr.addch(y_start, x_start + i, ' ')
            if text_color:
                stdscr.addstr(y_start, x_start, text, curses.A_BOLD | text_color)
            else:
                stdscr.addstr(y_start, x_start, text, curses.A_BOLD)
        except curses.error:
            pass


def gradient_rgb(index, total):
    if total <= 1:
        return (255, 140, 66)
    t = index / (total - 1)
    r = int(255 + (224 - 255) * t)
    g = int(140 + (123 - 140) * t)
    b = int(66 + (57 - 66) * t)
    return (r, g, b)


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(1)
    stdscr.timeout(100)

    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        COLOR_GREEN = curses.color_pair(1)
        COLOR_RED = curses.color_pair(2)

        GRAY_PAIR = 0
        if curses.COLORS >= 256:
            try:
                curses.init_pair(20, 244, curses.COLOR_BLACK)
                GRAY_PAIR = curses.color_pair(20)
            except curses.error:
                curses.init_pair(11, curses.COLOR_WHITE, curses.COLOR_BLACK)
                GRAY_PAIR = curses.color_pair(11) | curses.A_DIM
        else:
            curses.init_pair(11, curses.COLOR_WHITE, curses.COLOR_BLACK)
            GRAY_PAIR = curses.color_pair(11) | curses.A_DIM

        logo_lines = LOGO
        logo_count = len(logo_lines)
        gradient_pairs = []
        if curses.can_change_color() and curses.COLORS >= 256:
            for i in range(logo_count):
                r, g, b = gradient_rgb(i, logo_count)
                color_num = 3 + i
                try:
                    curses.init_color(color_num, r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)
                    curses.init_pair(color_num, color_num, curses.COLOR_BLACK)
                    gradient_pairs.append(curses.color_pair(color_num))
                except curses.error:
                    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
                    gradient_pairs = [curses.color_pair(3)] * logo_count
                    break
        else:
            curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
            gradient_pairs = [curses.color_pair(3)] * logo_count
    else:
        COLOR_GREEN = 0
        COLOR_RED = 0
        GRAY_PAIR = 0
        gradient_pairs = [0] * len(LOGO)

    wrapper = WarpWrapper()
    wrapper.start()
    show_ip = False

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            logo_lines = LOGO
            logo_height = len(logo_lines)
            start_row = 1
            block_width = max(len(line) for line in logo_lines) if logo_lines else 0
            left_margin = max(0, (width - block_width) // 2)
            max_draw = min(logo_height, height - 6)
            for i in range(max_draw):
                line = logo_lines[i]
                pair = gradient_pairs[i] if i < len(gradient_pairs) else gradient_pairs[-1]
                try:
                    stdscr.addstr(start_row + i, left_margin, line[:width - left_margin], pair)
                except curses.error:
                    pass

            logo_bottom = start_row + max_draw
            usable_top = logo_bottom + 1
            usable_bottom = height - 4
            center_y = (usable_top + usable_bottom) // 2 if usable_bottom > usable_top else height // 2
            center_x = width // 2
            radius = 5

            with wrapper.lock:
                raw_status = wrapper.status
                confirming = wrapper.confirming
                connected_confirmed = wrapper.connected_confirmed
                disconnecting = wrapper.disconnecting
                disconnected_confirmed = wrapper.disconnected_confirmed

            if confirming:
                display_status = "Connecting"
            elif disconnecting:
                display_status = "Disconnecting"
            elif "Connected" in raw_status and connected_confirmed:
                display_status = "Connected"
            elif "Disconnected" in raw_status and disconnected_confirmed:
                display_status = "Disconnected"
            else:
                display_status = raw_status[:12]

            if display_status == "Connecting":
                spin_angle = (time.time() * 200) % 360
                draw_circle(stdscr, center_y, center_x, radius, display_status,
                            spin_angle=spin_angle, spin_width=50,
                            highlight_color=0, base_color=GRAY_PAIR,
                            text_color=GRAY_PAIR)
            elif display_status == "Disconnecting":
                spin_angle = (time.time() * 200) % 360
                draw_circle(stdscr, center_y, center_x, radius, display_status,
                            spin_angle=spin_angle, spin_width=50,
                            highlight_color=GRAY_PAIR, base_color=0,
                            text_color=GRAY_PAIR)
            elif display_status == "Connected":
                draw_circle(stdscr, center_y, center_x, radius, display_status,
                            outline_color=0, text_color=0)
            elif display_status == "Disconnected":
                draw_circle(stdscr, center_y, center_x, radius, display_status,
                            outline_color=GRAY_PAIR, text_color=GRAY_PAIR)
            else:
                draw_circle(stdscr, center_y, center_x, radius, display_status,
                            outline_color=0, text_color=0)

            footer_y = height - 3

            protected = display_status == "Connected"
            protection_label = "Protected" if protected else "Unprotected"
            with wrapper.lock:
                current_ip = wrapper.ip
            ip_text = current_ip if show_ip else "***.***.***.***"
            status_text_left = f"[h] {protection_label}: {ip_text}"
            try:
                stdscr.addstr(footer_y, 2, status_text_left[:max(0, width - 4)])
            except curses.error:
                pass

            controls_text = "[c] Connect   [d] Disconnect   [q] Quit"
            controls_x = max(0, width - len(controls_text) - 2)
            try:
                stdscr.addstr(footer_y, controls_x, controls_text, GRAY_PAIR)
            except curses.error:
                pass

            key = stdscr.getch()
            if key == ord('q'):
                break
            elif key == ord('c'):
                wrapper.connect()
            elif key == ord('d'):
                wrapper.disconnect()
            elif key == ord('h'):
                show_ip = not show_ip

            stdscr.refresh()
    finally:
        wrapper.stop()


if __name__ == "__main__":
    curses.wrapper(main)
    