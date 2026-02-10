#!/usr/bin/env python3
"""
teleop_hold.py
Hold-to-drive teleop for Waveshare WAVE ROVER via JSON-over-serial.

- Works well over SSH terminals (no true key-up events needed)
- Holding keys generates repeated keypresses -> we treat that as "held"
- If you stop pressing keys, commands decay to 0 quickly -> rover stops

Keys:
  w/s : forward/back
  a/d : left/right turn
  x   : stop immediately
  q   : quit
"""

import time
import json
import threading
import serial
import curses

# --------- CONFIG ---------
PORT = "/dev/ttyTHS1"   # change to /dev/ttyUSB0 if using USB serial
BAUD = 115200

SEND_HZ = 30            # heartbeat command rate
KEY_HOLD_S = 0.18       # if no repeat within this time, key considered released
DEADMAN_S = 0.50        # absolute safety: no input at all -> stop (extra insurance)

MAX_X = 0.35            # m/s
MAX_Z = 1.5             # rad/s
# --------------------------

lock = threading.Lock()
x_cmd = 0.0
z_cmd = 0.0
last_any_key_time = time.time()

# key "expires" (if now > expire -> treated as not held)
w_exp = s_exp = a_exp = d_exp = 0.0


def send_cmd(ser, x, z):
    # Waveshare ROS velocity control format
    msg = {"T": 13, "X": float(x), "Z": float(z)}
    ser.write((json.dumps(msg) + "\n").encode("utf-8"))


def control_loop(ser):
    global x_cmd, z_cmd, last_any_key_time
    dt = 1.0 / SEND_HZ

    while True:
        now = time.time()
        with lock:
            x = x_cmd
            z = z_cmd
            t_any = last_any_key_time

        # absolute deadman safety
        if now - t_any > DEADMAN_S:
            x, z = 0.0, 0.0

        try:
            send_cmd(ser, x, z)
        except Exception:
            pass

        time.sleep(dt)


def ui_loop(stdscr):
    global x_cmd, z_cmd, last_any_key_time, w_exp, s_exp, a_exp, d_exp

    curses.curs_set(0)
    stdscr.nodelay(True)      # getch() won't block
    stdscr.keypad(True)

    stdscr.addstr(0, 0, "WAVE ROVER Teleop (hold-to-drive over SSH)")
    stdscr.addstr(2, 0, "Hold: w/s forward/back, a/d turn. Release -> stops.")
    stdscr.addstr(3, 0, "x stop, q quit")
    stdscr.addstr(5, 0, f"PORT={PORT}  BAUD={BAUD}  SEND={SEND_HZ}Hz  KEY_HOLD={KEY_HOLD_S}s")

    while True:
        now = time.time()

        # read as many queued keypresses as available this tick
        ch = stdscr.getch()
        quit_now = False
        stop_now = False
        got_any = False

        while ch != -1:
            got_any = True
            if ch == ord('w'):
                w_exp = now + KEY_HOLD_S
            elif ch == ord('s'):
                s_exp = now + KEY_HOLD_S
            elif ch == ord('a'):
                a_exp = now + KEY_HOLD_S
            elif ch == ord('d'):
                d_exp = now + KEY_HOLD_S
            elif ch == ord('x'):
                stop_now = True
            elif ch == ord('q'):
                quit_now = True
            ch = stdscr.getch()

        # determine "held" status from timers
        w_on = now <= w_exp
        s_on = now <= s_exp
        a_on = now <= a_exp
        d_on = now <= d_exp

        # compute commands independently: forward/back + turn can both be active
        new_x = 0.0
        new_z = 0.0

        if stop_now:
            new_x, new_z = 0.0, 0.0
            # also clear holds
            w_exp = s_exp = a_exp = d_exp = 0.0
            got_any = True  # counts as activity
        else:
            # X: if both held, cancel out (0). If one held, choose that direction.
            if w_on and not s_on:
                new_x = +MAX_X
            elif s_on and not w_on:
                new_x = -MAX_X
            else:
                new_x = 0.0

            # Z: same idea
            if a_on and not d_on:
                new_z = +MAX_Z
            elif d_on and not a_on:
                new_z = -MAX_Z
            else:
                new_z = 0.0

        with lock:
            x_cmd = new_x
            z_cmd = new_z
            if got_any:
                last_any_key_time = now

        # display
        stdscr.addstr(7, 0, f"Held: W={w_on} S={s_on} A={a_on} D={d_on}          ")
        stdscr.addstr(8, 0, f"Cmd:  X={new_x:+.2f} m/s   Z={new_z:+.2f} rad/s        ")
        stdscr.addstr(9, 0, f"Last input age: {now - last_any_key_time:.2f}s (deadman {DEADMAN_S}s)     ")
        stdscr.refresh()

        if quit_now:
            # stop on exit
            with lock:
                x_cmd = 0.0
                z_cmd = 0.0
                last_any_key_time = time.time()
            return

        time.sleep(0.02)


def main():
    ser = serial.Serial(PORT, BAUD, timeout=0.05)

    threading.Thread(target=control_loop, args=(ser,), daemon=True).start()

    curses.wrapper(ui_loop)

    # after UI exits, send a couple stop commands for safety
    try:
        send_cmd(ser, 0.0, 0.0)
        time.sleep(0.05)
        send_cmd(ser, 0.0, 0.0)
    except Exception:
        pass


if __name__ == "__main__":
    main()
