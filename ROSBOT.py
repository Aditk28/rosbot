import serial
import argparse
import threading
import json
import curses
from enum import Enum
import time

PORT = "/dev/ttyTHS1"   # change to /dev/ttyUSB0 if using USB serial
BAUD = 115200

SEND_HZ = 30            # heartbeat command rate
KEY_HOLD_S = 0.18       # if no repeat within this time, key considered released
DEADMAN_S = 0.50      

lock = threading.Lock()

class speed(Enum):
    LOW: 0
    MED: 0.25
    HIGH: 0.5

def read_serial():
    while True:
        data = ser.readline().decode('utf-8')
        if data:
            print(f"Received: {data}", end='')

def control_loop():
    global x_cmd, z_cmd, last_any_key_time
    dt = 1.0 / SEND_HZ

    while True:
        now = time.time()
        with lock:
            L_cmd = L
            R_cmd = R
            t_any = last_any_key_time

        # absolute deadman safety
        if now - t_any > DEADMAN_S:
            L_cmd, R_cmd = 0.0, 0.0

        try:
            send_command(L_cmd, R_cmd)
        except Exception:
            pass

        time.sleep(dt)

def ui_loop(stdscr):
    global L, R, last_any_key_time, w_exp, s_exp, a_exp, d_exp

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


        if stop_now:
            new_L, new_R = 0.0, 0.0
            # also clear holds
            w_exp = s_exp = a_exp = d_exp = 0.0
            got_any = True  # counts as activity
        else:
            # X: if both held, cancel out (0). If one held, choose that direction.
            if w_on and not s_on:
                new_R = speed.HIGH
                new_L = speed.HIGH
            elif s_on and not w_on:
                new_R = -speed.MED
                new_L = -speed.MED
            elif a_on and not d_on:
                new_R = speed.HIGH
                new_L = -speed.HIGH

            elif d_on and not a_on:
                new_R = -speed.HIGH
                new_L = speed.HIGH
            else:
                new_L = speed.LOW
                new_R = speed.LOW

        with lock:
            L = new_L
            R = new_R
            if got_any:
                last_any_key_time = now

        # display
        stdscr.addstr(7, 0, f"Held: W={w_on} S={s_on} A={a_on} D={d_on}          ")
        stdscr.addstr(8, 0, f"Cmd:  X={new_L:+.2f} m/s   Z={new_R:+.2f} rad/s        ")
        stdscr.addstr(9, 0, f"Last input age: {now - last_any_key_time:.2f}s (deadman {DEADMAN_S}s)     ")
        stdscr.refresh()

        if quit_now:
            # stop on exit
            with lock:
                L = speed.LOW
                R = speed.LOW
                last_any_key_time = time.time()
            return

        time.sleep(0.02)


def main():
    global ser
    parser = argparse.ArgumentParser(description='Serial JSON Communication')
    parser.add_argument('port', type=str, help='Serial port name (e.g., COM1 or /dev/ttyUSB0)')


    args = parser.parse_args()

    ser = serial.Serial(args.port, baudrate=115200, dsrdtr=None)


    threading.Thread(target=control_loop, args=(ser,), daemon=True).start()

    curses.wrapper(ui_loop)

    # after UI exits, send a couple stop commands for safety
    try:
        send_command(0.0, 0.0)
        time.sleep(0.05)
        send_command(0.0, 0.0)
    except Exception:
        pass


if __name__ == "__main__":
    main()


    ser.setRTS(False)
    ser.setDTR(False)

    serial_recv_thread = threading.Thread(target=read_serial)
    serial_recv_thread.daemon = True
    serial_recv_thread.start()

    try:
        while True:
            command = input("")
            ser.write(command.encode() + b'\n')
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == "__main__":
    main()

global L_speed
global R_speed


def send_command(L, R):
    command_dict = {"T":1,"L":L,"R":R}
    json_cmd = json.dumps((command_dict), '\n')
    ser.write((json.dumps(json_cmd) + "\n").encode("utf-8"))


