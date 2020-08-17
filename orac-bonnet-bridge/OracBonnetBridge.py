#!/usr/bin/env python3

# OracBonnetBridge.py - Orac <-> Adafruit OLED Bonnet bridge daemon. (https://github.com/TheTechnobear/Orac)


# Copyright (C) 2020 Nick Allott (https://github.com/neonmik)
#
# This program was built on the hardwork of Vilniaus Blokas UAB, https://blokas.io/
# Full thanks to work done in the original 
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2 of the
# License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import sys
import os
import threading

import board
import busio
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306

import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)

import argparse
import random
from threading import Timer
from enum import IntEnum
from time import sleep

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc import osc_message_builder
from pythonosc import udp_client

parser = argparse.ArgumentParser()
parser.add_argument("--ip", default="127.0.0.1", help="The IP of the Orac Display server")
parser.add_argument("--port", type=int, default=6100, help="The port the Orac Display server is listening on")
parser.add_argument("--listen", type=int, default=6111, help="The default port to listen for responses.")
args = parser.parse_args()

# Create the I2C interface.
i2c = busio.I2C(board.SCL, board.SDA)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
oled.fill(0)
oled.show()


class Menu:

    def __init__(self, options=[]):
        self.options = options
        self.highlightOption = None

        self.oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

        self.image = Image.new('1', (self.oled.width, self.oled.height))
        
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.truetype(os.path.dirname(__file__) + '/pixel_arial_11.ttf', 8)

        self.renderThread = None
        self.viewWidth = 128
        
    def set_options(self, options=[]):
        self.options = options
        self.rowCount = len(options)

    def set_highlight(self, highlight):
        if highlight is None:
            self.highlightOption = None
        elif highlight < 0:
            self.highlightOption = 0
        elif highlight >= len(self.options):
            self.highlightOption = len(self.options) - 1
        else:
            self.highlightOption = highlight

    def blank(self, draw=False):
        self.draw.rectangle((-1, 11, self.oled.width+1, self.oled.height+1), outline=0, fill=0)
        if draw:
            self.draw.rectangle((-1, -1, self.oled.width+1, self.oled.height+1), outline=0, fill=0)
            self.oled.image(self.image)
            self.oled.show()

    def run(self):
        if self.renderThread is None or not self.renderThread.isAlive():
            self.renderThread = threading.Thread(target=self.__run)
            self.renderThread.start()

    def __run(self):
        
        self.blank()
        self.__build()
        self.oled.image(self.image)
        self.oled.show()

    def __build(self):
        if (self.highlightOption is None) or (self.highlightOption < self.rowCount):
            start = 0
            end = self.rowCount
        elif self.highlightOption >= (len(self.options) - self.rowCount):
            end = len(self.options)
            start = end - self.rowCount
        else:
            start = self.highlightOption
            end = start + self.rowCount
        
        # Draw the Title option
        self.draw.rectangle([0, 0, 127, 11], outline=1, fill=0)
        self.draw.text((3, 1), "I: : : : : : : : : : O: : : : : : : : : : ", font=self.font, fill=1)
        
        # Draw the Menu options
        top = 11
        
        for x in range(start, end):
            fill = 1
            if self.highlightOption is not None and self.highlightOption == x:
                self.draw.rectangle([0, top, self.viewWidth, top + 11], outline=0, fill=1)
                fill = 0
            self.draw.text((3, top + 1), self.options[x], font=self.font, fill=fill)
            top += 10
        
    def end(self):
        self.blank(True)
        self.oled.image(self.image)
        self.oled.show()
        


class Orac:
    MAX_LINES = 6
    MAX_PARAMS = 8

    def __init__(self, ip, port):
        self.lines = [""]*Orac.MAX_LINES
        self.selectedLine = 0
        
        self.runThread = None

        self.params = [{"name": "", "value": "", "ctrl": 0.0} for _ in range(Orac.MAX_PARAMS)]

        self.oscDispatcher = Dispatcher()

        self.oscDispatcher.map("/text", self.textHandler)
        self.oscDispatcher.map("/selectText", self.selectTextHandler)
        self.oscDispatcher.map("/clearText", self.clearTextHandler)
        self.oscDispatcher.map("/P*Desc", self.paramDescHandler)
        self.oscDispatcher.map("/P*Ctrl", self.paramCtrlHandler)
        self.oscDispatcher.map("/P*Value", self.paramValueHandler)
        self.oscDispatcher.map("/module", self.moduleHandler)
        self.oscDispatcher.map("/*", self.allOtherHandler)


        self.server = ThreadingOSCUDPServer(('', args.listen), self.oscDispatcher)

        self.client = udp_client.SimpleUDPClient(args.ip, args.port)
        self.client.send_message("/Connect", args.listen)
        
        self.linesClearedCallbacks = []
        self.lineChangedCallbacks = []
        self.paramNameChangedCallbacks = []
        self.paramValueChangedCallbacks = []
        self.paramCtrlChangedCallbacks = []

        self.lineChangedNotificationsEnabled = True
        self.screenTimer = None
        self.linesSnapshot = None

        self.paramNotificationsEnabled = True
        self.paramTimer = None
        self.paramsSnapshot = None

        self.changingModule = False
        
    def navigationActivate(self):
        self.client.send_message("/NavActivate", 1.0)

    def navigationNext(self):
        self.client.send_message("/NavNext", 1.0)

    def navigationPrevious(self):
        self.client.send_message("/NavPrev", 1.0)
        
    def clearParams(self, reallyClear):
        self.paramNotificationsEnabled = False

        if self.paramTimer != None:
            self.paramTimer.cancel()
        else:
            self.paramsSnapshot = self.params.copy()

        self.paramTimer = Timer(0.2, self.handleParamUpdate, args=(reallyClear,))
        self.paramTimer.start()

        self.params = [{"name": "", "value": "", "ctrl": 0.0} for _ in range(Orac.MAX_PARAMS)]

    def handleParamUpdate(self, reallyClear):
        if self.params == [{"name": "", "value": "", "ctrl": 0.0} for _ in range(Orac.MAX_PARAMS)]:
            if not reallyClear:
                self.params = self.paramsSnapshot
            else:
                for i in range(Orac.MAX_PARAMS):
                    self.notifyParamNameChanged(i, "")
                    self.notifyParamValueChanged(i, "")
                    self.notifyParamCtrlChanged(i, None)
        else:
            for i in range(Orac.MAX_PARAMS):
                if self.paramsSnapshot[i]["name"] != self.params[i]["name"]:
                    self.notifyParamNameChanged(i, self.params[i]["name"])
                if self.paramsSnapshot[i]["value"] != self.params[i]["value"]:
                    self.notifyParamValueChanged(i, self.params[i]["value"])
                self.notifyParamCtrlChanged(i, self.params[i]["ctrl"] if self.params[i]["name"] or self.params[i]["value"] else None)

        self.paramNotificationsEnabled = True
        self.paramTimer = None
        self.paramsSnapshot = None

    def moduleNext(self):
        self.changingModule = True
        self.client.send_message("/ModuleNext", 1.0)

    def modulePrevious(self):
        self.changingModule = True
        self.client.send_message("/ModulePrev", 1.0)

    def pageNext(self):
        self.clearParams(False)
        self.client.send_message("/PageNext", 1.0)

    def pagePrevious(self):
        self.clearParams(False)
        self.client.send_message("/PagePrev", 1.0)
        
    def paramSet(self, param, value):
        value = max(min(value, 1.0), 0.0)
        self.client.send_message("/P%dCtrl" % (param+1), value)
        if self.paramNotificationsEnabled:
            self.notifyParamCtrlChanged(param, value)

    def addLinesClearedCallback(self, cb):
        self.linesClearedCallbacks.append(cb)

    def addLineChangedCallback(self, cb):
        self.lineChangedCallbacks.append(cb)

    def addParamNameChangedCallback(self, cb):
        self.paramNameChangedCallbacks.append(cb)

    def addParamValueChangedCallback(self, cb):
        self.paramValueChangedCallbacks.append(cb)

    def addParamCtrlChangedCallback(self, cb):
        self.paramCtrlChangedCallbacks.append(cb)

    def notifyLinesCleared(self):
        for cb in self.linesClearedCallbacks:
            cb(self)

    def notifyLineChanged(self, line, text, selected):
        for cb in self.lineChangedCallbacks:
            cb(self, line, text, selected)

    def notifyParamNameChanged(self, i, name):
        for cb in self.paramNameChangedCallbacks:
            cb(self, i, name)

    def notifyParamValueChanged(self, i, value):
        for cb in self.paramValueChangedCallbacks:
            cb(self, i, value)

    def notifyParamCtrlChanged(self, i, ctrl):
        for cb in self.paramCtrlChangedCallbacks:
            cb(self, i, ctrl)

    def run(self):
        if self.runThread is None or not self.runThread.isAlive():
            self.runThread = threading.Thread(target=self.__run)
            self.runThread.start()

    def __run(self):
        self.server.serve_forever(0.1)

    def textHandler(self, address, *osc_arguments):
        i = osc_arguments[0]-1
        if self.lines[i] != osc_arguments[1]:
            self.lines[i] = osc_arguments[1]
            if self.lineChangedNotificationsEnabled:
                self.notifyLineChanged(i, self.lines[i], self.selectedLine == i)

    def selectTextHandler(self, address, *osc_arguments):
        i = osc_arguments[0]-1
        if self.selectedLine != i:
            if self.lineChangedNotificationsEnabled:
                self.notifyLineChanged(self.selectedLine, self.lines[self.selectedLine], False)
            self.selectedLine = i
            if self.lineChangedNotificationsEnabled:
                self.notifyLineChanged(i, self.lines[i], True)
        
    def handleScreenUpdate(self):
        if self.lines == [""]*Orac.MAX_LINES:
            self.notifyLinesCleared()
        else:
            for i in range(Orac.MAX_LINES):
                if self.linesSnapshot[i] != self.lines[i]:
                    self.notifyLineChanged(i, self.lines[i], i == self.selectedLine)

        self.lineChangedNotificationsEnabled = True
        self.screenTimer = None
        
    def clearTextHandler(self, address, *osc_arguments):
        if self.changingModule:
            self.clearParams(True)

        self.lineChangedNotificationsEnabled = False

        if self.screenTimer != None:
            self.screenTimer.cancel()
        else:
            self.linesSnapshot = self.lines.copy()

        self.screenTimer = Timer(0.2, self.handleScreenUpdate)
        self.screenTimer.start()

        self.lines = [""]*Orac.MAX_LINES

    @staticmethod
    def decodeParamId(oscAddress):
        return ord(oscAddress[2]) - ord('1')


    def paramDescHandler(self, address, *osc_arguments):
        i = Orac.decodeParamId(address)
        if self.params[i]["name"] != osc_arguments[0]:
            self.params[i]["name"] = osc_arguments[0]
            if self.paramNotificationsEnabled:
                self.notifyParamNameChanged(i, osc_arguments[0])

    def paramValueHandler(self, address, *osc_arguments):
        i = Orac.decodeParamId(address)
        if self.params[i]["value"] != osc_arguments[0]:
            self.params[i]["value"] = osc_arguments[0]
            if self.paramNotificationsEnabled:
                self.notifyParamValueChanged(i, osc_arguments[0])

    def moduleHandler(self, address, *osc_arguments):
        self.changingModule = False

    def paramCtrlHandler(self, address, *osc_arguments):
        i = Orac.decodeParamId(address)
        if self.params[i]["ctrl"] != osc_arguments[0]:
            self.params[i]["ctrl"] = osc_arguments[0]
            if self.paramNotificationsEnabled:
                self.notifyParamCtrlChanged(i, osc_arguments[0])

    def allOtherHandler(self, address, *osc_arguments):
        pass
        
    def end(self):
        self.server.server_close()
        
        

class OracCtl:
    class Button(IntEnum):
        B           = 5
        A           = 6
        Centre      = 4
        Right       = 23
        Down        = 22
        Left        = 27
        Up          = 17

    

    def __init__(self, menu, Controller):
        self.blank = menu.blank
        self.paramList = ["", "", "", ""]
        self.printList = ["", "", "", "", ""]
        self.highlightList = ["", "", "", "", ""]
                
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(22, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(4, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(23, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(27, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(6, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(5, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self.inputCallbacks = []
        
        
    def inputCallback(self, channel):
        down = True
        self.notifyInput(OracCtl.Button(channel), down)

    def __del__(self):
        self.clearScreen()
        GPIO.cleanup()

    def addInputCallback(self, callback):
        self.inputCallbacks.append(callback)

    def notifyInput(self, button, down):
        for c in self.inputCallbacks:
            c(self, button, down)

    def printLine(self, line, text, inverted):

        self.highlightDefine = 0
        if inverted is True:
            self.highlightDefine = int(line)
            menu.set_highlight(self.highlightDefine)
        
        if line < 5:
            self.printList[line] = (text)
        if line >= 5:
            print(text)
        
        menu.set_options(self.printList)
        
        
        

    def printParam(self, i, name, value, inverted):
        
        self.highlightDefine = 0
        if inverted is True:
            self.highlightDefine = int(i)
            menu.set_highlight(self.highlightDefine)
            
        if not name or not value:
            self.paramList[i] = ("")
        else:
            self.paramList[i] = ("%s: %s" % (name, value))
        menu.set_options(self.paramList)
        
        
            
        
        
    def printCtrl(self, i, ctrl, inverted): # Print a control data
        pass


    def deleteCtrl(self, i): # Clear control data
        pass


    def clearScreen(self): # Clear OLED with draw.blank()
        self.blank()

    def setViewMode(self, mode): # <--- set screen width, 128 for ctrl, 104 for params
        if mode != 2:
            menu.viewWidth = 128
        else:
            menu.blank()
            menu.viewWidth = 128

class Controller:
    class Mode(IntEnum):
        UNKNOWN = 0
        MENU    = 1
        PARAMS  = 2

    def __init__(self, orac, oracCtl):
        self.mode = Controller.Mode.UNKNOWN
        self.lines = [{"text": "", "inverted": False} for _ in range(Orac.MAX_LINES)]
        self.params = [{"name": "", "value": "", "ctrl": 0.0} for _ in range(Orac.MAX_PARAMS)]
        self.selectedParam = 0
        self.changingParam = None

        self.orac = orac
        self.oracCtl = oracCtl
        self.oracCtl.addInputCallback(self.onButtonEvent)
        self.orac.addLineChangedCallback(self.onLineChanged)
        self.orac.addLinesClearedCallback(self.onLinesCleared)
        self.orac.addParamNameChangedCallback(self.onParamNameChanged)
        self.orac.addParamValueChangedCallback(self.onParamValueChanged)
        self.orac.addParamCtrlChangedCallback(self.onParamCtrlChanged)

        self.setMode(Controller.Mode.MENU)

    def isParamDefined(self, param):
        return self.params[param]["name"] or self.params[param]["value"]

    def setMode(self, mode):
        if self.mode == mode:
            return

        self.oracCtl.clearScreen()
        self.oracCtl.setViewMode(mode)

        if mode == Controller.Mode.MENU:
            for i in range(Orac.MAX_LINES):
                self.oracCtl.printLine(i, self.lines[i]["text"], self.lines[i]["inverted"])
                
        elif mode == Controller.Mode.PARAMS:
            paramFound = False
            self.selectedParam = 0
            self.changingParam = None
            for i in range(Orac.MAX_PARAMS):
                if self.isParamDefined(i):
                    paramFound = True
                    self.oracCtl.printParam(i, self.params[i]["name"], self.params[i]["value"], i == self.selectedParam)
                    self.oracCtl.printCtrl(i, self.params[i]["ctrl"], i == self.selectedParam)
            if not paramFound:
                self.oracCtl.printLine(0,"", False)
                self.oracCtl.printLine(1, "      This module has", False)
                self.oracCtl.printLine(2, "         no params!", False)
                self.oracCtl.printLine(3,"", False)
                self.oracCtl.printLine(4,"", False)
                

        self.mode = mode

    def onLinesCleared(self, sender):
        self.lines = [{"text": "", "inverted": False} for _ in range(Orac.MAX_LINES)]
        if self.mode == Controller.Mode.MENU:
            self.oracCtl.clearScreen()

    def onLineChanged(self, sender, line, text, inverted):
        self.lines[line]["text"] = text
        self.lines[line]["inverted"] = inverted
        if self.mode == Controller.Mode.MENU:
            self.oracCtl.printLine(line, text, inverted)

    def onParamNameChanged(self, sender, i, name):
        self.params[i]["name"] = name
        if self.mode == Controller.Mode.PARAMS:
            self.oracCtl.printParam(i, self.params[i]["name"], self.params[i]["value"], i == self.selectedParam and self.changingParam == None)

    def onParamValueChanged(self, sender, i, value):
        self.params[i]["value"] = value
        if self.mode == Controller.Mode.PARAMS:
            self.oracCtl.printParam(i, self.params[i]["name"], self.params[i]["value"], i == self.selectedParam and self.changingParam == None)

    def onParamCtrlChanged(self, sender, i, ctrl):
        self.params[i]["ctrl"] = ctrl
        if self.mode == Controller.Mode.PARAMS:
            if self.isParamDefined(i):
                self.oracCtl.printCtrl(i, self.params[i]["ctrl"], i == self.selectedParam)
            else:
                self.oracCtl.deleteCtrl(i)

    def selectNextParam(self):
        prev = self.selectedParam
        self.changingParam = None
        if self.selectedParam+1 < Orac.MAX_PARAMS and self.isParamDefined(self.selectedParam+1):
            self.selectedParam += 1
        else:
            return

        if self.mode == Controller.Mode.PARAMS:
            self.oracCtl.printParam(prev, self.params[prev]["name"], self.params[prev]["value"], False)
            self.oracCtl.printCtrl(prev, self.params[prev]["ctrl"], False)
            self.oracCtl.printParam(self.selectedParam, self.params[self.selectedParam]["name"], self.params[self.selectedParam]["value"], True)
            self.oracCtl.printCtrl(self.selectedParam, self.params[self.selectedParam]["ctrl"], True)

    def selectPrevParam(self):
        prev = self.selectedParam
        self.changingParam = None
        if self.selectedParam > 0:
            self.selectedParam -= 1
        else:
            return

        if self.mode == Controller.Mode.PARAMS:
            self.oracCtl.printParam(prev, self.params[prev]["name"], self.params[prev]["value"], False)
            self.oracCtl.printCtrl(prev, self.params[prev]["ctrl"], False)
            self.oracCtl.printParam(self.selectedParam, self.params[self.selectedParam]["name"], self.params[self.selectedParam]["value"], True)
            self.oracCtl.printCtrl(self.selectedParam, self.params[self.selectedParam]["ctrl"], True)

    def increaseParam(self, param):
        if not self.isParamDefined(param):
            return
        orac.paramSet(param, self.params[param]["ctrl"] + 4 / 127.0)
        return

    def decreaseParam(self, param):
        if not self.isParamDefined(param):
            return
        orac.paramSet(param, self.params[param]["ctrl"] - 4 / 127.0)
        return

    def activateParam(self, param):
        if not self.isParamDefined(param):
            return

        self.changingParam = param
        self.oracCtl.printParam(param, self.params[param]["name"], self.params[param]["value"], False)
        self.oracCtl.printCtrl(param, self.params[param]["ctrl"], True)

        # Make a dummy change so this param can be mapped.
        orac.paramSet(param, self.params[param]["ctrl"])

    def deactivateParam(self):
        self.changingParam = None
        self.oracCtl.printParam(self.selectedParam, self.params[self.selectedParam]["name"], self.params[self.selectedParam]["value"], True)
        self.oracCtl.printCtrl(self.selectedParam, self.params[self.selectedParam]["ctrl"], True)

    def onButtonEvent(self, sender, button, down):
        if not down:
            print("Not Down")
            return

        if button == OracCtl.Button.B:
            self.setMode(Controller.Mode.MENU if self.mode == Controller.Mode.PARAMS else Controller.Mode.PARAMS)
            return

        if self.mode == Controller.Mode.MENU:
            if button == OracCtl.Button.Centre:
                self.orac.navigationActivate()
            elif button == OracCtl.Button.Up:
                self.orac.navigationPrevious()
            elif button == OracCtl.Button.Down:
                self.orac.navigationNext()
            elif button == OracCtl.Button.Left:
                self.orac.modulePrevious()
            elif button == OracCtl.Button.Right:
                self.orac.moduleNext()
            
        elif self.mode == Controller.Mode.PARAMS:
            if button == OracCtl.Button.Down:
                self.selectNextParam()
            elif button == OracCtl.Button.Up:
                self.selectPrevParam()
            elif button == OracCtl.Button.Right:
                if self.changingParam == None:
                    self.selectedParam = 0
                    self.orac.pageNext()
                else:
                    self.increaseParam(self.selectedParam)
            elif button == OracCtl.Button.Left:
                if self.changingParam == None:
                    self.selectedParam = 0
                    self.orac.pagePrevious()
                else:
                    self.decreaseParam(self.selectedParam)
            elif button == OracCtl.Button.A:
                if self.changingParam == None:
                    self.activateParam(self.selectedParam)
                else:
                    self.deactivateParam()



menu = Menu (["", "", "              Loading...", "", "",])
orac = Orac(args.ip, args.port)
oracCtl = OracCtl(menu, Controller)
ctrl = Controller(orac, oracCtl)

GPIO.add_event_detect(17, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)
GPIO.add_event_detect(22, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)
GPIO.add_event_detect(4, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)
GPIO.add_event_detect(23, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)
GPIO.add_event_detect(27, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)
GPIO.add_event_detect(6, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)
GPIO.add_event_detect(5, GPIO.FALLING, callback=oracCtl.inputCallback, bouncetime=150)


try:
    
    print("Server Starting")

    
    while True:
        orac.run()
        menu.run()


finally:
    menu.end()
    orac.end()
    del ctrl
    del oracCtl
    del orac
    GPIO.cleanup()
    print("Cleaned up and done!")
    raise SystemExit
