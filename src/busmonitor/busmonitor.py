#! /usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH
#
"""
CAN BusMonitor — migrated from simplyCAN to the pycan generic API.

Supports backends: TLV-UDP, ASCII-TCP, ASCII-UDP, VCI (IXXAT).
"""

import tempfile
import os.path
import sys
import time
import threading
import json
import tkinter as tk
from tkinter import Tk

from busmonitor.lib import monitorGUI

# Ensure pycan is importable (editable install or src on path)
try:
    from pycan.can_api import (
        BusState,
        CanApi,
        CanApiError,
        CanFilter,
        CanMessage,
        CanTiming,
        ControllerConfig,
        FrameFormat,
        FrameType,
        IdentifierFormat,
        OpenConfig,
        Transport,
    )
    from pycan.canudp import CanUdp
    from pycan.ascii_can import AsciiCan
    if sys.platform == "win32":
        try:
            from pycan.vci_can import VciCan
        except ImportError:
            VciCan = None
    else:
        VciCan = None
except ImportError:
    # Allow running from source tree without install
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pycan"))
    from can_api import (
        BusState,
        CanApi,
        CanApiError,
        CanFilter,
        CanMessage,
        CanTiming,
        ControllerConfig,
        FrameFormat,
        FrameType,
        IdentifierFormat,
        OpenConfig,
        Transport,
    )
    from canudp import CanUdp
    from ascii_can import AsciiCan
    VciCan = None

monitorGUI.kToolVersion = "2.0.0"
monitorGUI.kABOUT = """
www.ixxat.com

IXXAT pyCAN BusMonitor v%s
(pycan API backend)

Copyright (c) 2018 - 2025
HMS Technology Center GmbH
All rights reserved.""" % monitorGUI.kToolVersion

kTitle = "pyCAN BusMonitor"
kSETTINGSFILE = "canmonitor_settings.json"

BACKENDS = ["tlv-udp", "ascii-tcp", "ascii-udp"]
if VciCan is not None:
    BACKENDS.append("vci")
DEFAULT_PORTS = {
    "tlv-udp": 19236,
    "ascii-tcp": 19228,
    "ascii-udp": 19228,
}
CAN_PORT = 1


class CanMonitor(monitorGUI.monitorGUI):
    """
    Main Application — pycan based pyCAN BusMonitor.
    """

    def __init__(self, root):
        tempdir = os.path.join(tempfile.gettempdir(), "canmonitor_history.txt")
        monitorGUI.monitorGUI.__init__(self, root, tempdir, kTitle)
        self.lLines = []
        self.traceEnabled = False
        self.tracefile = None
        self.receiveCnt = 0
        self.recOutput = []
        self.loggOutput = []
        self.devConnected = False
        self.canState = "stopped"
        self.autoscroll = True
        self.dataAvailable = False
        self.can_port = CAN_PORT
        self.last_error = 0
        self.api: CanApi | None = None
        self.timestamp_base: int = 0  # first timestamp_us for relative display

        self.cycleCnt = 0
        self.cycleTaskActive = True
        self.loggingTaskActive = True
        self.loc = threading.Lock()

        self.cycleTask = threading.Thread(target=self.cycle_task, daemon=True)
        self.cycleTask.start()
        self.loggingTask = threading.Thread(target=self.logging_task, daemon=True)
        self.loggingTask.start()
        self.root.after(100, self.onStart)

    # -----------------------------------------------------------------
    # Stored settings
    # -----------------------------------------------------------------
    def _get_stored_data(self):
        fname = os.path.join(tempfile.gettempdir(), kSETTINGSFILE)
        if os.path.exists(fname):
            try:
                return json.load(open(fname, "r"))
            except Exception:
                pass
        return {"backend": "tlv-udp", "address": "", "baudrate": "500", "can_port": "1", "data_baudrate": "---"}

    def _save_settings(self):
        fname = os.path.join(tempfile.gettempdir(), kSETTINGSFILE)
        data = {
            "backend": self.cbCommDevice.get(),
            "address": self.entAddress.get(),
            "baudrate": self.cbBaudrate.get(),
            "can_port": self.cbCanPort.get(),
            "data_baudrate": self.cbDataBaudrate.get(),
        }
        try:
            with open(fname, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Startup
    # -----------------------------------------------------------------
    def onStart(self):
        data = self._get_stored_data()
        self.cbCommDevice['values'] = BACKENDS
        self.cbBaudrate.set(data.get("baudrate", "500"))
        self.cbCommDevice.set(data.get("backend", "tlv-udp"))
        self.entAddress.delete(0, tk.END)
        self.entAddress.insert(0, data.get("address", ""))
        self.cbCanPort.set(data.get("can_port", "1"))
        self.cbDataBaudrate.set(data.get("data_baudrate", "---"))
        self.guiRefreshTargetDisconnected()
        self.refreshInfobar()
        self.root.after(1, self.cycle_gui)

    # -----------------------------------------------------------------
    # Transmit command parser
    # -----------------------------------------------------------------
    def execute(self, msg):
        """
        Parse transmit command: '<id> [R][E][F][B] [<data> ...]'
        Flags: E=extended, R=remote, F=FD (no BRS), B=FD+BRS
        """
        if not msg:
            return True

        items = msg.split()
        item_num = 0

        if len(items) < 1:
            self.write_output("Syntax error: <id> missing")
            self.onShowSyntax()
            return False

        ident_str = items[item_num]
        if not self.ishexdec(ident_str):
            self.write_output("Syntax error: Invalid <id> format")
            self.onShowSyntax()
            return False
        ident = self.str2int(ident_str) & 0x1FFFFFFF
        item_num += 1

        # Parse flags
        id_format = IdentifierFormat.STANDARD
        frame_format = FrameFormat.CLASSIC
        frame_type = FrameType.DATA

        if len(items) > item_num:
            flag_candidate = items[item_num].upper()
            if any(c in flag_candidate for c in "REFB"):
                item_num += 1
                if "E" in flag_candidate:
                    id_format = IdentifierFormat.EXTENDED
                if "R" in flag_candidate:
                    frame_type = FrameType.REMOTE
                if "B" in flag_candidate:
                    frame_format = FrameFormat.FD_BRS
                elif "F" in flag_candidate:
                    frame_format = FrameFormat.FD_NO_BRS

        # Auto-extend if id > 0x7FF
        if ident > 0x7FF:
            id_format = IdentifierFormat.EXTENDED

        # Parse data bytes
        datalist = []
        for item in items[item_num:]:
            if not self.ishexdec(item):
                self.write_output("Syntax error: Invalid <data ...> format")
                self.onShowSyntax()
                return False
            val = self.str2int(item)
            if val > 255:
                self.write_output("Syntax error: Value of data byte larger than 255")
                return False
            datalist.append(val)

        max_len = 64 if frame_format != FrameFormat.CLASSIC else 8
        if len(datalist) > max_len:
            datalist = datalist[:max_len]

        data = bytes(datalist)
        can_msg = CanMessage(ident, data, id_format, frame_format, frame_type)

        # Display in output
        self.write_output(self._format_message(can_msg, 0, self_sent=True))
        self.printReceive()

        # Send
        try:
            self.api.send(self.can_port, can_msg)
        except Exception as e:
            self.write_output(f"Send failed: {e}")
            return False
        return True

    # -----------------------------------------------------------------
    # Receive
    # -----------------------------------------------------------------
    def receive(self):
        """Read and display received messages."""
        if self.api is None:
            return
        for _ in range(200):
            try:
                msg = self.api.receive(self.can_port, timeout=0)
            except Exception:
                break
            if msg is None:
                break
            self.receiveCnt += 1
            ts_us = msg.timestamp_us or 0
            if self.timestamp_base == 0 and ts_us != 0:
                self.timestamp_base = ts_us
            rel_ms = (ts_us - self.timestamp_base) // 1000 if ts_us else 0
            output = self._format_message(msg, rel_ms)
            self.write_output(output)

    # -----------------------------------------------------------------
    # Message formatting
    # -----------------------------------------------------------------
    @staticmethod
    def _format_message(msg: CanMessage, timestamp_ms: int, self_sent: bool = False) -> str:
        flags = ""
        if self_sent:
            flags += "S"
        if msg.id_format == IdentifierFormat.EXTENDED:
            flags += "E"
        if msg.frame_type == FrameType.REMOTE:
            flags += "R"
        if msg.frame_format == FrameFormat.FD_BRS:
            flags += "B"
        elif msg.frame_format == FrameFormat.FD_NO_BRS:
            flags += "F"

        if msg.frame_type == FrameType.REMOTE:
            dlc = msg.dlc
            payload_hex = ""
            payload_ascii = ""
        else:
            dlc = len(msg.data)
            payload_hex = " ".join(f"{b:02X}" for b in msg.data)
            payload_ascii = "".join(chr(b) if 32 <= b <= 126 else "." for b in msg.data)

        return f"{timestamp_ms:010d}  {msg.can_id:<8X} {flags:<7s}[{dlc}]  {payload_hex:<27s}{payload_ascii}"

    # -----------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------
    def printReceive(self):
        if self.dataAvailable and len(self.recOutput) > 0:
            selected_items = list(map(int, self.lbOutput.curselection()))
            vw = self.lbOutput.yview()
            self.lbOutput.delete(0, last="end")
            for item in self.recOutput:
                self.lbOutput.insert("end", item)
            if self.autoscroll:
                self.lbOutput.see("end")
            else:
                self.lbOutput.yview_moveto(vw[0])
                for item in selected_items:
                    self.lbOutput.selection_set(item)
            self.dataAvailable = False

    def refreshInfobar(self):
        if self.devConnected:
            if self.canState == "started":
                self.writeInfobar(f"Device: connected   |   CAN started   |   RX count: {self.receiveCnt}")
            else:
                self.writeInfobar("Device: connected   |   CAN stopped")
        else:
            self.writeInfobar("Device: disconnected")

    # -----------------------------------------------------------------
    # Tasks
    # -----------------------------------------------------------------
    def cycle_gui(self):
        self.printReceive()
        if self.cycleCnt % 10 == 0:
            self.RefreshGui()
        self.root.after(100, self.cycle_gui)
        self.cycleCnt += 1

    def logging_task(self):
        while self.loggingTaskActive:
            if self.traceEnabled and len(self.loggOutput) > 0:
                output_string = ""
                self.loc.acquire()
                for entry in self.loggOutput:
                    output_string += entry + "\n"
                self.loggOutput = []
                self.loc.release()
                try:
                    with open(self.tracefile, "a") as f:
                        f.write(output_string)
                except Exception:
                    pass
            time.sleep(0.01)

    def cycle_task(self):
        while self.cycleTaskActive:
            if self.devConnected and self.canState == "started":
                self.receive()
            time.sleep(0.001)

    # -----------------------------------------------------------------
    # GUI helpers
    # -----------------------------------------------------------------
    def RefreshGui(self):
        if self.devConnected:
            self.guiRefreshTargetConnected()
            if self.canState == "started":
                self.targetmenu.entryconfig(monitorGUI.dMenuEntries["CAN start"], state=tk.DISABLED)
                self.targetmenu.entryconfig(monitorGUI.dMenuEntries["CAN stop"], state=tk.ACTIVE)
                if self.bCanStart["state"] != tk.DISABLED:
                    self.bCanStart.configure(state=tk.DISABLED)
                if self.bCanStop["state"] != tk.ACTIVE:
                    self.bCanStop.configure(state=tk.ACTIVE)
                self.cbTransmit.configure(state=tk.NORMAL)
                if self.bSend["state"] != tk.NORMAL:
                    self.bSend.configure(state=tk.NORMAL)
                self.cbBaudrate.configure(state=tk.DISABLED)
                self.cbDataBaudrate.configure(state=tk.DISABLED)
                # Update status LEDs from bus state
                self._update_status_leds()
            else:
                self.targetmenu.entryconfig(monitorGUI.dMenuEntries["CAN start"], state=tk.ACTIVE)
                self.targetmenu.entryconfig(monitorGUI.dMenuEntries["CAN stop"], state=tk.DISABLED)
                if self.bCanStart["state"] != tk.NORMAL:
                    self.bCanStart.configure(state=tk.NORMAL)
                if self.bCanStop["state"] != tk.DISABLED:
                    self.bCanStop.configure(state=tk.DISABLED)
                self.cbBaudrate.configure(state=tk.NORMAL)
                self.cbBaudrate["state"] = "readonly"
                self.cbDataBaudrate.configure(state=tk.NORMAL)
                self.cbDataBaudrate["state"] = "readonly"
                if self.bSend["state"] != tk.DISABLED:
                    self.bSend.configure(state=tk.DISABLED)
                self.cbTransmit.configure(state=tk.DISABLED)
                # CAN stopped — all LEDs white
                self.imgCAN['image'] = self.button_white_icon
                self.imgPending['image'] = self.button_white_icon
                self.imgOverrun['image'] = self.button_white_icon
                self.imgWarning['image'] = self.button_white_icon
                self.imgBusoff['image'] = self.button_white_icon
        else:
            self.guiRefreshTargetDisconnected()
        self.refreshInfobar()

    def _update_status_leds(self):
        """Query bus state from API and update the status LED indicators."""
        try:
            status = self.api.get_status(self.can_port)
        except Exception:
            return
        state = status.state

        # CAN active LED
        if state == BusState.RUNNING:
            self.imgCAN['image'] = self.button_green_icon
        else:
            self.imgCAN['image'] = self.button_white_icon

        # Pending (TX queue has data)
        if status.tx_free == 0 and state == BusState.RUNNING:
            self.imgPending['image'] = self.button_orange_icon
        else:
            self.imgPending['image'] = self.button_white_icon

        # Overrun
        if state == BusState.OVERRUN:
            self.imgOverrun['image'] = self.button_orange_icon
        else:
            self.imgOverrun['image'] = self.button_white_icon

        # Warning (error passive or warning)
        if state in (BusState.ERROR_WARNING, BusState.ERROR_PASSIVE):
            self.imgWarning['image'] = self.button_orange_icon
        else:
            self.imgWarning['image'] = self.button_white_icon

        # Bus-off
        if state == BusState.BUS_OFF:
            self.imgBusoff['image'] = self.button_red_icon
        else:
            self.imgBusoff['image'] = self.button_white_icon

    def handleAPIError(self, error_string):
        self.write_output(error_string)

    def write_output(self, outputString, logging=True):
        if len(self.recOutput) > 1000:
            self.recOutput.pop(0)
        self.recOutput.append(outputString)
        self.dataAvailable = True
        if logging and self.traceEnabled:
            self.loc.acquire()
            self.loggOutput.append(outputString)
            self.loc.release()

    # -----------------------------------------------------------------
    # Connect / Disconnect
    # -----------------------------------------------------------------
    def onTargetConnect(self):
        backend = self.cbCommDevice.get()
        address = self.entAddress.get().strip()
        can_port_str = self.cbCanPort.get().strip()
        self.can_port = int(can_port_str) if can_port_str else 1

        if not backend:
            self.write_output("Error: Select a backend type")
            return
        if not address:
            self.write_output("Error: Enter an IP address or device serial")
            return

        port = DEFAULT_PORTS.get(backend, 19236)

        try:
            if backend == "tlv-udp":
                self.api = CanUdp(host=address, port=port)
                self.api.open(OpenConfig(transport=Transport.UDP, address=address, port=port))
            elif backend == "ascii-tcp":
                self.api = AsciiCan(host=address, port=port, transport=Transport.TCP, device_family="nt")
                self.api.open(OpenConfig(transport=Transport.TCP, address=address, port=port, options={"device_family": "nt"}))
            elif backend == "ascii-udp":
                self.api = AsciiCan(host=address, port=port, transport=Transport.UDP, device_family="basic")
                self.api.open(OpenConfig(transport=Transport.UDP, address=address, port=port, options={"device_family": "basic"}))
            elif backend == "vci" and VciCan is not None:
                self.api = VciCan()
                self.api.open(OpenConfig(transport=Transport.VCI, device_id=address))
            else:
                self.write_output(f"Unknown backend: {backend}")
                return
        except Exception as e:
            self.write_output(f"Connect failed: {e}")
            if self.api:
                try:
                    self.api.close()
                except Exception:
                    pass
                self.api = None
            return

        self.devConnected = True
        self.lblProductStringTextVar.set(f"{backend}")
        self.lblSerialNumberTextVar.set(address)
        self.lblHWVersionTextVar.set(f"CAN port: {self.can_port}")
        self.lblFWVersionTextVar.set("")
        self.RefreshGui()

    def onTargetDisconnect(self):
        self.DisconnectTarget()
        self.RefreshGui()

    def DisconnectTarget(self):
        self.devConnected = False
        if self.canState != "stopped" and self.api:
            try:
                self.api.stop_can(self.can_port)
            except Exception:
                pass
        self.canState = "stopped"
        if self.api:
            try:
                self.api.close()
            except Exception:
                pass
            self.api = None

    # -----------------------------------------------------------------
    # CAN Start / Stop
    # -----------------------------------------------------------------
    def onCanStart(self):
        baudrate_str = self.cbBaudrate.get()
        bitrate = int(baudrate_str) if baudrate_str.isdigit() else 0
        if bitrate <= 0:
            self.write_output("Invalid bitrate")
            return

        # FD data bitrate
        data_baudrate_str = self.cbDataBaudrate.get()
        data_bitrate = int(data_baudrate_str) if data_baudrate_str.isdigit() else 0

        if data_bitrate > 0:
            cfg = ControllerConfig(
                can_fd=True,
                bitrate_switch=True,
                arbitration=CanTiming(bitrate_kbit=bitrate),
                data=CanTiming(bitrate_kbit=data_bitrate),
            )
        else:
            cfg = ControllerConfig(arbitration=CanTiming(bitrate_kbit=bitrate))
        accept_all = [
            CanFilter(IdentifierFormat.STANDARD, mask=0, value=0),
            CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0),
        ]

        try:
            try:
                self.api.stop_can(self.can_port)
            except Exception:
                pass
            self.api.init_can(self.can_port, cfg)
            for f in accept_all:
                self.api.add_filter(self.can_port, f)
            self.api.start_can(self.can_port)
        except Exception as e:
            self.write_output(f"CAN start failed: {e}")
            return

        self.canState = "started"
        self.receiveCnt = 0
        self.timestamp_base = 0
        self.RefreshGui()

    def onCanStop(self):
        try:
            self.api.stop_can(self.can_port)
        except Exception as e:
            self.write_output(f"CAN stop failed: {e}")
            return
        self.canState = "stopped"
        self.RefreshGui()

    # -----------------------------------------------------------------
    # Misc callbacks
    # -----------------------------------------------------------------
    def onRefreshDevices(self):
        pass  # No COM scanning needed

    def onTransmit(self, cmnd):
        cmnd = cmnd.strip()
        if cmnd:
            self.execute(cmnd)

    def onTraceLocation(self):
        tracefile = self.askSaveAsFile()
        if tracefile is not None:
            self.tracefile = tracefile.name
            return True
        return False

    def onTraceEnable(self):
        state = self.menuEnableTracing.get()
        if state and self.tracefile is None:
            if self.onTraceLocation():
                self.traceEnabled = True
            else:
                self.traceEnabled = False
                self.menuEnableTracing.set(False)
        else:
            self.traceEnabled = state
        if self.traceEnabled:
            try:
                with open(self.tracefile, "a") as f:
                    f.write("Time(ms)    ID(hex)  Flags  DLC  Data (hex)                 ASCII\n")
            except Exception:
                pass

    def onAutoscrollEnable(self):
        self.autoscroll = self.menuAutoscroll.get()

    def onShowSyntax(self):
        self.write_output("Syntax:", logging=False)
        self.write_output("  Send message: '<id> [R][E][F][B] [<data> ...]'", logging=False)
        self.write_output("", logging=False)
        self.write_output("where", logging=False)
        self.write_output("      id            CAN identifier, e.g. '100' or '0x100'.", logging=False)
        self.write_output("      data          Data bytes, e.g. '1 2 0x55 0x56'.", logging=False)
        self.write_output("", logging=False)
        self.write_output("  Flags:", logging=False)
        self.write_output("      S             Self-reception (message sent by this tool).", logging=False)
        self.write_output("      E             Extended frame format (29 bit).", logging=False)
        self.write_output("      R             Remote transmit request.", logging=False)
        self.write_output("      F             CAN FD frame (no BRS).", logging=False)
        self.write_output("      B             CAN FD frame with BRS.", logging=False)
        self.write_output("", logging=False)

    def onExit(self):
        self.cycleTaskActive = False
        self.loggingTaskActive = False

        if self.canState != "stopped" and self.api:
            try:
                self.api.stop_can(self.can_port)
            except Exception:
                pass
        if self.api:
            try:
                self.api.close()
            except Exception:
                pass

        self._save_settings()

        try:
            lines = self.cbTransmit["values"]
            with open(self.his_file_name, "wt") as f:
                f.write("\n".join(lines))
        except Exception:
            pass
        self.root.running = False
        sys.exit()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def ishexdec(self, s):
        try:
            int(s.strip(), 16)
            return True
        except Exception:
            return False

    def str2int(self, s):
        try:
            return int(s.strip(), 16)
        except Exception:
            return 0


def main():
    root = Tk()
    root.running = True
    CanMonitor(root)
    while True:
        if root.running:
            root.update_idletasks()
            root.update()
        else:
            root.destroy()
            break
        time.sleep(0.001)


if __name__ == "__main__":
    main()
