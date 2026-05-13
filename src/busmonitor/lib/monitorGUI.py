#! /usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH
#
"""
GUI for the busmonitor tool
"""

#--------------- Import Section --------------------------------------------
from tkinter import *
import tkinter as tk
from tkinter.filedialog import asksaveasfile
from tkinter import ttk
from busmonitor.lib import icons

kToolVersion = "Toolversion number e.g. V0.5.0"
kABOUT = "This is the About box"
# ^^^, defined in the main routine busmonitor.py

dMenuEntries = {
### Menu 'File'
"Enable Tracing":                      "   Enable tracing                                              ",
"Location of trace file...":           "   Location of trace file...                                   ",
"Exit":                                "   Exit                                                  Ctrl+Q",
### Menu 'View'
"Clear output window":                 "   Clear output window         ",
"Clear transmit history":              "   Clear transmit history      ",
"Autoscroll output window":            "   Autoscroll output window    ",
### Menu 'Target'
"Connect the target":                  "   Connect the target      ",
"Disconnect the target":               "   Disconnect the target   ",
"CAN start":                           "   CAN start               ",
"CAN stop":                            "   CAN stop                ",
### Menu 'Help'
"Show Syntax":                         "   Show Syntax      ",
"About":                               "   About            ",
}

"""
Implementation of the monitor GUI class
""" 
class monitorGUI(object):
    def __init__(self, root, his_file_name, title):
        """
        Initialization of the GUI
        """             
        self.root = root
        self.his_file_name = his_file_name        
        self.monitor_icon = tk.PhotoImage(data=icons.monitor_icon)                        
        self.button_green_icon = tk.PhotoImage(data=icons.button_green_icon20x20)
        self.button_white_icon = tk.PhotoImage(data=icons.button_white_icon20x20)
        self.button_orange_icon = tk.PhotoImage(data=icons.button_orange_icon20x20)
        self.button_red_icon = tk.PhotoImage(data=icons.button_red_icon20x20)       
        self.ixxat_logo = tk.PhotoImage(data=icons.ixxat_logo)       
        self.hms_color = '#043D5D'

        root.minsize(600, 500)
        root.title(title)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.geometry('1000x600')
        root.protocol("WM_DELETE_WINDOW", self.onExit)
        root.tk.call('wm', 'iconphoto', root._w, self.monitor_icon)
        ttk.Sizegrip(root).grid(column=0, row=999, sticky=(S,E))
        root.bind_all("<Control-q>", self.onKeyboardQuit)
        self.layout(root)

    def onKeyboardQuit(self, event):
        self.onExit()

    def layout(self, root):
        """
        root
        - Menu
        - mainframe
          - left_frame
            - layout_left
          - right_frame
            - output_frame
            - transmit_frame
        - Infobar
        """
        self.menu(root)

        # mainframe
        mainframe = ttk.Frame(root)        
        mainframe.grid(column=0, row=0, sticky=(N,W,E,S))
        mainframe.columnconfigure(1, weight=1)
        mainframe.rowconfigure(0, weight=1)        

        # left_frame
        left_frame_pre = ttk.Frame(mainframe)
        left_frame_pre['padding'] = (5,5)
        left_frame_pre.grid(column=0, row=0, sticky=(N,W,E,S))
        left_frame_pre.rowconfigure(0, weight=1)

        left_frame = LabelFrame(left_frame_pre, text='Device Control:', foreground=self.hms_color)
        left_frame.grid(column=0, row=0, sticky=(N,W,E,S))
        left_frame.rowconfigure(2, weight=1)

        # right_frame
        right_frame = ttk.Frame(mainframe)
        right_frame['padding'] = (5,5)
        right_frame.grid(column=1, row=0, sticky=(N,W,E,S))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)
        
        # implement the left layout
        self.layout_left(left_frame)

        # implement the output and transmit frames
        c1 = self.output_frame(right_frame)
        c1.columnconfigure(0, weight=1)
        c2 = self.transmit_frame(right_frame)
        c2.columnconfigure(0, weight=1)

        # implement the infobar layout
        separator = ttk.Separator(root, orient=HORIZONTAL)
        separator.grid(column=0, row=998, sticky=(N,W,E,S))
        self.lblInfobar = ttk.Label(root, text='Device: connected', relief=FLAT, anchor=W)
        self.lblInfobar.grid(column=0, row=999, sticky=(N,W,E,S))
        self.lblInfobar['padding'] = (1,1)

    def menu(self, root):
        """
        Menu
        - File
            - Enable Tracing
            - Location of trace file...
            - Exit
        - View
            - Clear output window
            - Clear transmit window
            - Autoscroll output window
        - Target
            - Connect the target
            - Disconnect the target
            - CAN start
            - CAN stop
        - Help
            - Show syntax
            - About
        """

        # Creat Menu
        menubar = Menu(root)
        root.config(menu=menubar)

        # File menu
        self.filemenu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=self.filemenu)
        self.menuEnableTracing = BooleanVar(root)
        self.filemenu.add_checkbutton(label=dMenuEntries["Enable Tracing"], variable=self.menuEnableTracing, command=self.onTraceEnable if hasattr(self, "onTraceEnable") else self.EventNotImplemented)
        self.filemenu.add_command(    label=dMenuEntries["Location of trace file..."], command=self.onTraceLocation if hasattr(self, "onTraceLocation") else self.EventNotImplemented)
        self.filemenu.add_separator()
        self.filemenu.add_command(    label=dMenuEntries["Exit"], command=self.onExit if hasattr(self, "onExit") else self.EventNotImplemented)

        # View menu
        viewmenu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=viewmenu)
        self.menuAutoscroll = BooleanVar(root)
        self.menuAutoscroll.set(True)
        viewmenu.add_command(label=dMenuEntries["Clear output window"], command=self.clear_lbOutput)
        viewmenu.add_command(label=dMenuEntries["Clear transmit history"],  command=self.clearTransmitHistory)
        viewmenu.add_checkbutton(label=dMenuEntries["Autoscroll output window"], variable=self.menuAutoscroll, command=self.onAutoscrollEnable if hasattr(self, "onAutoscrollEnable") else self.EventNotImplemented)

        # Target menu
        self.targetmenu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Target", menu=self.targetmenu)
        #self.targetmenu.add_command(label="   Settings", command=self.EventNotImplemented)
        #self.targetmenu.add_separator()
        self.targetmenu.add_command(label=dMenuEntries["Connect the target"], command=self.onTargetConnect if hasattr(self, "onTargetConnect") else self.EventNotImplemented)
        self.targetmenu.add_command(label=dMenuEntries["Disconnect the target"], command=self.onTargetDisconnect if hasattr(self, "onTargetDisconnect") else self.EventNotImplemented)
        self.targetmenu.add_separator()
        self.targetmenu.add_command(label=dMenuEntries["CAN start"], command=self.onCanStart if hasattr(self, "onCanStart") else self.EventNotImplemented)
        self.targetmenu.add_command(label=dMenuEntries["CAN stop"], command=self.onCanStop if hasattr(self, "onCanStop") else self.EventNotImplemented)

        # Help menu
        helpmenu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=helpmenu)
        helpmenu.add_command(label=dMenuEntries["Show Syntax"], command=self.onShowSyntax if hasattr(self, "onShowSyntax") else self.EventNotImplemented)
        helpmenu.add_command(label=dMenuEntries["About"], command=self.aboutDialog if hasattr(self, "aboutDialog") else self.EventNotImplemented)

    def layout_left(self, parent):
        """
        Creates the left frame
        - row_1
            - label 'lblCommDevice'
            - combobox 'cbCommDevice'
            - label 'lblBaudrate'
            - combobox 'cbBaudrate'
        - row_2
            - button 'bConnect'
            - button 'bDisonnect'
            - button 'bRefreshDevices'
        - row_3
            - todo HMS logo
        - row_4
            - button 'bCanStart'
            - button 'bCanStop'
        - row_5
            - CAN status
        """

        def on_enter(e):
            w1['background'] = '#d8e6f2'

        def on_leave(e):
            w1['background'] = 'SystemButtonFace'

        def rClicker(e, value):
            if (value == None or value == ''):
                return
            try:
                def rClick_Copy(e, apnd=0):
                    e.widget.event_generate('<Control-c>')
                def rClick_Cut(e):
                    e.widget.event_generate('<Control-x>')
                def rClick_Paste(e):
                    e.widget.event_generate('<Control-v>')
                e.widget.focus()
                nclst=[
                       #(' Cut', lambda e=e: rClick_Cut(e)),
                       (' Copy', lambda e=e: rClick_Copy(e)),
                       #(' Paste', lambda e=e: rClick_Paste(e)),
                       ]
                rmenu = Menu(None, tearoff=0, takefocus=0)
                for (txt, cmd) in nclst:
                    rmenu.add_command(label=txt, command=cmd)
                rmenu.tk_popup(e.x_root+40, e.y_root+10,entry="0")
            except TclError:
                pass
            return "break"

        #####
        # Frame 'row_1'
        #####
        row_1 = ttk.Frame(parent)        
        row_1.grid(column=0, row=0, sticky=(N, W, E, S))

        # Label 'lblBackend'
        lblBackend = ttk.Label(row_1, text='Backend:')
        lblBackend.grid(column=0, row=0, sticky=(N, W, E, S))
        # Combobox 'cbCommDevice' (backend type selector)
        self.cbCommDevice = ttk.Combobox(row_1, state="readonly", textvariable=StringVar())
        self.cbCommDevice['values'] = ('tlv-udp', 'ascii-tcp', 'ascii-udp', 'virtual')
        self.cbCommDevice.grid(column=1, row=0, sticky=(N, W, E, S))

        # Label 'lblAddress'
        lblAddress = ttk.Label(row_1, text='IP Address:')
        lblAddress.grid(column=0, row=1, sticky=(N, W, E, S))
        # Entry 'entAddress'
        self.entAddress = ttk.Entry(row_1)
        self.entAddress.grid(column=1, row=1, sticky=(N, W, E, S))

        # Label 'lblCanPort'
        lblCanPort = ttk.Label(row_1, text='CAN Port:')
        lblCanPort.grid(column=0, row=2, sticky=(N, W, E, S))
        # Combobox 'cbCanPort'
        self.cbCanPort = ttk.Combobox(row_1, state="readonly", textvariable=StringVar(), width=5)
        self.cbCanPort['values'] = ('1', '2', '3', '4')
        self.cbCanPort.set('1')
        self.cbCanPort.grid(column=1, row=2, sticky=(N, W, E, S))

        for child in row_1.winfo_children(): child.grid_configure(padx=5, pady=5)

        #####
        # Frame 'row_2'
        #####
        row_2 = ttk.Frame(parent)        
        row_2.grid(column=0, row=1, sticky=(N, W, E, S))
        row_2.grid(column=0, row=1)

        # Button 'bConnectbConnect'
        self.bConnect = ttk.Button(row_2, text='Connect', command=self.onTargetConnect if hasattr(self, "onTargetConnect") else self.EventNotImplemented)
        self.bConnect.grid(column=0, row=2, sticky=(N, W, E, S))
        # Button 'bDisconnect'
        self.bDisconnect = ttk.Button(row_2, text='Disconnect', command=self.onTargetDisconnect if hasattr(self, "onTargetDisconnect") else self.EventNotImplemented)
        self.bDisconnect.grid(column=1, row=2, sticky=(N, W, E, S))        
        self.bDisconnect.configure(state=tk.DISABLED)

        for child in row_2.winfo_children(): 
            child.grid_configure(padx=5, pady=5)

        #####
        # Frame 'row_3'
        #####
        row_3 = ttk.Frame(parent)
        row_3.grid(column=0, row=2, sticky=(N,W,E,S))
        row_3['padding'] = (5,5)

        imgLogo = ttk.Label(row_3, image=self.ixxat_logo)
        imgLogo.grid(column=0, row=0, sticky=(N,W,E,S))
        imgLogo['padding'] = (0,10)

        self.lblProductStringTextVar = StringVar()
        self.lblProductStringTextVar.set("")
        self.lblProductString = Entry(row_3,textvariable=self.lblProductStringTextVar,bd=0,state="readonly")
        self.lblProductString.grid(column=0, row=1, sticky=(N, W, E, S))
        self.lblProductString.bind('<Button-3>', lambda event: rClicker(event, self.lblProductStringTextVar.get()))

        self.lblSerialNumberTextVar = StringVar()
        self.lblSerialNumberTextVar.set("")
        self.lblSerialNumber = Entry(row_3,textvariable=self.lblSerialNumberTextVar,bd=0,state="readonly")
        self.lblSerialNumber.grid(column=0, row=2, sticky=(N, W, E, S))
        self.lblSerialNumber.bind('<Button-3>', lambda event: rClicker(event, self.lblSerialNumberTextVar.get()))

        self.lblHWVersionTextVar = StringVar()
        self.lblHWVersionTextVar.set("")
        self.lblHWVersion = Entry(row_3,textvariable=self.lblHWVersionTextVar,bd=0,state="readonly")
        self.lblHWVersion.grid(column=0, row=3, sticky=(N, W, E, S))
        self.lblHWVersion.bind('<Button-3>', lambda event: rClicker(event, self.lblHWVersionTextVar.get()))

        self.lblFWVersionTextVar = StringVar()
        self.lblFWVersionTextVar.set("")
        self.lblFWVersion = Entry(row_3,textvariable=self.lblFWVersionTextVar,bd=0,state="readonly")
        self.lblFWVersion.grid(column=0, row=4, sticky=(N, W, E, S))
        self.lblFWVersion.bind('<Button-3>', lambda event: rClicker(event, self.lblFWVersionTextVar.get()))


        #####
        # Frame 'row_4'
        #####
        row_4 = ttk.Frame(parent, relief=FLAT)
        row_4.grid(column=0, row=3, sticky=(N,W,E,S))

        # Label 'lblBaudrate'
        lblBaudrate = ttk.Label(row_4, text='Baudrate [kBaud]:')
        lblBaudrate.grid(column=0, row=1, sticky=(N, W, E, S))
        # Combobox 'cbBaudrate'
        self.cbBaudrate = ttk.Combobox(row_4, state="readonly", textvariable=StringVar())        
        self.cbBaudrate.grid(column=1, row=1, sticky=(N, W, E, S))
        self.cbBaudrate['values'] = ('10', '20', '50', '125', '250', '500', '800', '1000')

        # Label 'lblDataBaudrate'
        lblDataBaudrate = ttk.Label(row_4, text='FD Data [kBaud]:')
        lblDataBaudrate.grid(column=0, row=2, sticky=(N, W, E, S))
        # Combobox 'cbDataBaudrate'
        self.cbDataBaudrate = ttk.Combobox(row_4, state="readonly", textvariable=StringVar())
        self.cbDataBaudrate.grid(column=1, row=2, sticky=(N, W, E, S))
        self.cbDataBaudrate['values'] = ('---', '1000', '2000', '4000', '5000', '8000')

        for child in row_4.winfo_children(): child.grid_configure(padx=5, pady=5)

        #####
        # Frame 'row_5'
        #####
        row_5 = ttk.Frame(parent, relief=FLAT)
        row_5.grid(column=0, row=4, sticky=(N,W,E,S))
        row_5.columnconfigure(3, weight=1)

        # Button 'bCanStart'
        self.bCanStart = ttk.Button(row_5, text='CAN start', command=self.onCanStart if hasattr(self, "onCanStart") else self.EventNotImplemented)
        self.bCanStart.grid(column=0, row=1)
        self.bCanStart.configure(state=tk.DISABLED)
        # Button 'bCanStop'
        self.bCanStop = ttk.Button(row_5, text='CAN stop', command=self.onCanStop if hasattr(self, "onCanStop") else self.EventNotImplemented)
        self.bCanStop.grid(column=1, row=1)
        self.bCanStop.configure(state=tk.DISABLED)           
        for child in row_5.winfo_children(): child.grid_configure(padx=5, pady=5)

        #####
        # Frame 'row_6'
        #####
        row_6 = ttk.Frame(parent, relief=FLAT)
        row_6.grid(column=0, row=5, sticky=(N,W,E,S))
        row_6.columnconfigure(0, weight=1)

        ampel_frame = LabelFrame(row_6, text='CAN status:', foreground=self.hms_color)        
        ampel_frame['padx'] = 5
        ampel_frame['pady'] = 5
        ampel_frame.grid(column=0, row=0, sticky=(N,W,E,S))
        ampel_frame.columnconfigure(0, weight=1)
        ampel_frame.columnconfigure(1, weight=1)
        ampel_frame.columnconfigure(2, weight=1)
        ampel_frame.columnconfigure(3, weight=1)
        ampel_frame.columnconfigure(4, weight=1)


        w1 = ttk.Label(ampel_frame, text='CAN')
        w1.grid(column=0, row=0)
        self.imgCAN = ttk.Label(ampel_frame, image=self.button_white_icon)
        self.imgCAN.grid(column=0, row=1)
        ttp_imgCAN = CreateToolTip(self.imgCAN, \
        "LED off: CAN stopped\n"
        "LED green: CAN active")

        w1 = ttk.Label(ampel_frame, text='Pend')
        w1.grid(column=1, row=0)
        self.imgPending = ttk.Label(ampel_frame, image=self.button_white_icon)
        self.imgPending.grid(column=1, row=1)
        CreateToolTip(self.imgPending,
                      "LED off: All messages transmitted\n"
                      "LED orange: At least one transmit message is pending")

        w1 = ttk.Label(ampel_frame, text='Ovr')
        w1.grid(column=2, row=0)
        self.imgOverrun = ttk.Label(ampel_frame, image=self.button_white_icon)
        self.imgOverrun.grid(column=2, row=1)
        CreateToolTip(self.imgOverrun,
                      "LED orange: Data overrun occurred (frame lost)")

        w1 = ttk.Label(ampel_frame, text='Warn')
        w1.grid(column=3, row=0)
        self.imgWarning = ttk.Label(ampel_frame, image=self.button_white_icon)
        self.imgWarning.grid(column=3, row=1)
        CreateToolTip(self.imgWarning,
                      "LED red: Error warning level reached")

        w1 = ttk.Label(ampel_frame, text='B.off')
        w1.grid(column=4, row=0)
        self.imgBusoff = ttk.Label(ampel_frame, image=self.button_white_icon)
        self.imgBusoff.grid(column=4, row=1)
        CreateToolTip(self.imgBusoff,
                      "LED red: Bus off status")
        for child in row_6.winfo_children(): child.grid_configure(padx=5, pady=2)
        
    def output_frame(self, parent):
        """
        Creates the output frame
        - output_frame
            - frame
              - label 'header'
              - listbox 'lbOutput'
            - scrollbar
        """
        # Frame 'output_frame'
        output_frame = LabelFrame(parent, text='Output:', foreground=self.hms_color)
        output_frame.grid(column=0, row=0, sticky=(N,W,E,S))
        output_frame.rowconfigure(0, weight=1)
        output_frame['padx'] = 5
        output_frame['pady'] = 5
        output_frame['borderwidth'] = 1
        output_frame['relief'] = 'ridge'

        frame = ttk.Frame(output_frame, relief=RIDGE)
        frame.grid(column=0, row=0, sticky=(N,W,E,S))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame['borderwidth'] = 2

        # output header label
        header = ttk.Label(frame, font='TkFixedFont', background='#ffffff')
        header.grid(column=0, row=0, sticky=(N,W,E,S))    
        header['text'] = "Time(ms)    ID(hex)  Flags  DLC  Data (hex)                 ASCII"

        # Listbox 'lbOutput'
        self.lbOutput = Listbox(frame, font='TkFixedFont', exportselection=False)
        self.lbOutput.grid(column=0, row=1, sticky=(N,W,E,S))
        self.lbOutput['relief'] = 'flat'
        self.lbOutput['borderwidth'] = 0
        self.lbOutput['selectmode'] = EXTENDED

        # Scollbar 'sbOutput'
        self.sbOutput = ttk.Scrollbar(output_frame, orient=VERTICAL, command=self.lbOutput.yview)
        self.sbOutput.grid(column=1, row=0, sticky=(N,S))
        self.lbOutput['yscrollcommand'] = self.sbOutput.set
        return output_frame
    
    def transmit_frame(self, parent):
        """
        Creates the transmit frame
        - transmit_frame
            - combobox 'cbTransmit'
            - button 'bSend'
            - button 'bClear'
        """
        def callback(evt):
            val = self.cbTransmit.get().strip()
            if val == "": return
            values = list(self.cbTransmit['values'])
            if val in values:
                idx = values.index(val)
                del values[idx]
            values = [val] + values
            self.cbTransmit['values'] = tuple(values)
            if evt != None: # Enter key pressed
                self.cbTransmit.set("")
            if hasattr(self, "onTransmit"):
                self.onTransmit(val)
            else:
                self.lbOutput.insert('end', val)
        # Frame
        transmit_frame = LabelFrame(parent, text='Transmit:', foreground=self.hms_color)
        #transmit_frame['padding'] = (8,8)
        transmit_frame['padx'] = 8
        transmit_frame['pady'] = 8
        transmit_frame['borderwidth'] = 2
        transmit_frame['relief'] = 'ridge'
        transmit_frame.grid(column=0, row=2, sticky=(N,W,E,S))

        # Combobox 'cbTransmit'
        self.cbTransmit = ttk.Combobox(transmit_frame, textvariable=StringVar())
        try:
            lines = open(self.his_file_name).readlines()
            lines = [item.strip() for item in lines]
        except:
            lines = []
        self.cbTransmit['values'] = lines
        self.cbTransmit['height'] = 20
        self.cbTransmit.bind('<Return>', callback)
        self.cbTransmit.grid(column=0, row=0, sticky=(N, W, E, S))
        self.cbTransmit.configure(state=tk.DISABLED)

        # Button 'bSend'
        self.bSend = ttk.Button(transmit_frame, text='Send', command=lambda:callback(None))
        self.bSend.grid(column=1, row=0, sticky=(N, W, E, S))
        self.bSend.configure(state=tk.DISABLED)

        # Button 'bClear'
        self.bClear = ttk.Button(transmit_frame, text='Clear', command=self.clear_lbOutput)
        self.bClear.grid(column=2, row=0, sticky=(N, W, E, S))

        # Insert padding for each widget in the transmit_frame
        for child in transmit_frame.winfo_children(): 
            child.grid_configure(padx=5, pady=2)
        return transmit_frame

    def guiRefreshTargetDisconnected(self):
        """
        Refresh GUI if target is disconnected
        """
        self.targetmenu.entryconfig(dMenuEntries["Connect the target"], state=tk.ACTIVE)
        self.targetmenu.entryconfig(dMenuEntries["Disconnect the target"], state=tk.DISABLED)
        self.targetmenu.entryconfig(dMenuEntries["CAN start"], state=tk.DISABLED)
        self.targetmenu.entryconfig(dMenuEntries["CAN stop"], state=tk.DISABLED)

        self.cbCommDevice.configure(state=tk.NORMAL)
        self.cbCommDevice['state'] = "readonly"
        if hasattr(self, 'entAddress'):
            self.entAddress.configure(state=tk.NORMAL)
        if hasattr(self, 'cbCanPort'):
            self.cbCanPort.configure(state=tk.NORMAL)
            self.cbCanPort['state'] = "readonly"
        self.cbBaudrate.configure(state=tk.DISABLED)
        self.cbDataBaudrate.configure(state=tk.DISABLED)

        if self.bConnect['state'] != tk.NORMAL:
            self.bConnect.configure(state=tk.NORMAL)
        if self.bDisconnect['state'] != tk.DISABLED:
            self.bDisconnect.configure(state=tk.DISABLED)

        if self.bCanStart['state'] != tk.DISABLED:
            self.bCanStart.configure(state=tk.DISABLED)
        if self.bCanStop['state'] != tk.DISABLED:
            self.bCanStop.configure(state=tk.DISABLED)

        self.cbTransmit.configure(state=tk.DISABLED)

        if self.bSend['state'] != tk.DISABLED:
            self.bSend.configure(state=tk.DISABLED)

        self.imgCAN['image'] = self.button_white_icon
        self.imgPending['image'] = self.button_white_icon
        self.imgOverrun['image'] = self.button_white_icon
        self.imgWarning['image'] = self.button_white_icon
        self.imgBusoff['image'] = self.button_white_icon

        self.lblProductStringTextVar.set("")
        self.lblHWVersionTextVar.set("")
        self.lblFWVersionTextVar.set("")
        self.lblSerialNumberTextVar.set("")

    def guiRefreshTargetConnected(self):
        """
        Refresh GUI if target is connected
        """
        self.targetmenu.entryconfig(dMenuEntries["Connect the target"], state=tk.DISABLED)
        self.targetmenu.entryconfig(dMenuEntries["Disconnect the target"], state="active")
        self.targetmenu.entryconfig(dMenuEntries["CAN start"], state="active")
        self.targetmenu.entryconfig(dMenuEntries["CAN stop"], state=tk.DISABLED)
        
        self.cbCommDevice.configure(state=tk.DISABLED)
        if hasattr(self, 'entAddress'):
            self.entAddress.configure(state=tk.DISABLED)
        if hasattr(self, 'cbCanPort'):
            self.cbCanPort.configure(state=tk.DISABLED)
        self.cbBaudrate.configure(state=tk.NORMAL)
        self.cbBaudrate['state'] = "readonly"
        self.cbDataBaudrate.configure(state=tk.NORMAL)
        self.cbDataBaudrate['state'] = "readonly"
        if self.bConnect['state'] != tk.DISABLED:
            self.bConnect.configure(state=tk.DISABLED)
        if self.bDisconnect['state'] != tk.NORMAL:
            self.bDisconnect.configure(state=tk.NORMAL)

    def askSaveAsFile(self):   
        """
        Opens the SaveAsFile Dialog
        """
        return asksaveasfile(confirmoverwrite=False, mode = "a", defaultextension=".txt", title = "Select file", filetypes = (("text files","*.txt"),("all files","*.*")), initialdir=self.tracefile, initialfile=self.tracefile)        

    def write_lbOutput(self, text):
        """
        Write one line into the listbox 'lbOutput'
        """        
        self.lbOutput.insert('end', text.rstrip())
        self.lbOutput.see('end')

    def clear_lbOutput(self):
        """
        Clear all entries in the listbox 'lbOutput'
        """     
        self.lbOutput.delete(0, END)
        self.recOutput = []

    def writeInfobar(self, text):
        """
        Write to the Infobar
        """     
        self.lblInfobar['text'] = text

    def clearTransmitHistory(self):
        """
        Clear the history of the combobox 'cbTransmit'
        """    
        try:
            open(self.his_file_name, "w").write("")
        except:
            pass
        lines = []
        self.cbTransmit['values'] = lines

    def onExit(self):
        """
        Callbackfunction onExit
        """ 
        lines = self.cb['values']
        try:
            open(self.his_file_name, "wt").write("\n".join(lines))
        except:
            pass

    def aboutDialog(self):
        """
        Creat and open the about dialog
        """ 
        self.dlg = AboutDialog(self, "About IXXAT pyCAN BusMonitor", "360x200")

    def EventNotImplemented(self):
        """
        Standard callback function for unimplemented event callbacks
        """ 
        print("Event not implemented")

class HoverButton(tk.Button):
    def __init__(self, master, **kw):
        tk.Button.__init__(self,master=master,**kw)
        self.defaultBackground = self["background"]
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)

    def on_enter(self, e):
        self['background'] = self['activebackground']

    def on_leave(self, e):
        self['background'] = self.defaultBackground

"""
Implementation of the about dialog class
""" 
class AboutDialog(object):   
    def __init__(self, parent, title="Dialog", geometry="450x450"):
        """
        Initialization of the about dialog GUI
        """ 
        self.info_icon = tk.PhotoImage(data=icons.info_icon)
        dialog = Toplevel(parent.root)
        dialog.title(title)
        dialog.transient(parent.root) # hide minimize/maximize
        dialog.geometry(geometry)
        dialog.resizable(0,0)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        dialog.tk.call('wm', 'iconphoto', dialog._w, self.info_icon)
        
        self.centerDialog(parent.root, dialog)
        self.doLayout(dialog)       

    def doLayout(self, root):
        """
        Create the layout of the dialog
        - main_frame
            - Info icon
            - Info text
        - bottom_frame
            - Button
        """ 
        # Main Frame
        main_frame = ttk.Frame(root)        
        main_frame.grid(column=0, row=0, sticky=(N,W,E,S))        
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Bottom Frame
        bottom_frame = ttk.Frame(root)        
        bottom_frame.grid(column=0, row=1, sticky=(E))
        bottom_frame.rowconfigure(0, weight=1)
        bottom_frame['padding'] = (10,10)

        # Info icon
        w0 = ttk.Label(main_frame, background="white")
        w0.grid(column=0, row=0, sticky=(N, W, E, S))
        w1 = ttk.Label(main_frame, image=self.info_icon, background="white")
        w1.grid(column=0, row=0, sticky=(N))
        w1['padding'] = (10,10)

        # Info text
        w2 = ttk.Label(main_frame, background="white", text=kABOUT)        
        w2.grid(column=1, row=0, sticky=(N, W, E, S))

        # Bottom Button
        bOK = ttk.Button(bottom_frame, text="OK", command=lambda:root.destroy())
        bOK.grid(column=0, row=0, sticky=(E))        

    def centerDialog(self, root, dialog):
        """
        Center the position of the dialog window relative to the root window
        """ 
        dialog.update_idletasks()
        root.update_idletasks()

        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = root.winfo_x() + (root.winfo_width() // 2) - (width // 2)
        y = root.winfo_y() + (root.winfo_height() // 2) - (height // 2)

        dialog.geometry('{}x{}+{}+{}'.format(width, height, x, y))

class CreateToolTip(object):
    """
    create a tooltip for a given widget
    """
    def __init__(self, widget, text='widget info'):
        self.waittime = 500     #miliseconds
        self.wraplength = 180   #pixels
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        self.id = None
        self.tw = None

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.waittime, self.showtip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x = y = 0
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        # creates a toplevel window
        self.tw = tk.Toplevel(self.widget)
        # Leaves only the label and removes the app window
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(self.tw, text=self.text, justify='left',
                       background="#ffffff", relief='solid', borderwidth=1,
                       wraplength = self.wraplength)
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tw
        self.tw= None
        if tw:
            tw.destroy()
