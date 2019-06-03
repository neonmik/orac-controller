#!/usr/bin/env python3

# OracCtrlBridge.py - Orac <-> Midiboy bridge daemon. (https://github.com/TheTechnobear/Orac)
# Copyright (C) 2019  Vilniaus Blokas UAB, https://blokas.io/
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

import argparse
import random
import time
import rtmidi
from threading import Timer
from enum import IntEnum

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc import osc_message_builder
from pythonosc import udp_client

parser = argparse.ArgumentParser()
parser.add_argument("--ip", default="127.0.0.1", help="The IP of the Orac Display server")
parser.add_argument("--port", type=int, default=6100, help="The port the Orac Display server is listening on")
parser.add_argument("--listen", type=int, default=6111, help="The default port to listen for responses.")
args = parser.parse_args()

class Orac:
	MAX_LINES = 5
	MAX_PARAMS = 8

	def __init__(self, ip, port):
		self.lines = [""]*Orac.MAX_LINES
		self.selectedLine = 0

		self.params = [{"name": "", "value": "", "ctrl": 0.0} for _ in range(Orac.MAX_PARAMS)]

		self.oscDispatcher = Dispatcher()

		self.oscDispatcher.map("/text", self.textHandler)
		self.oscDispatcher.map("/selectText", self.selectTextHandler)
		self.oscDispatcher.map("/clearText", self.clearTextHandler)
		self.oscDispatcher.map("/P*Desc", self.paramDescHandler)
		self.oscDispatcher.map("/P*Ctrl", self.paramCtrlHandler)
		self.oscDispatcher.map("/P*Value", self.paramValueHandler)
		self.oscDispatcher.map("/*", self.allOtherHandler)

		self.server = BlockingOSCUDPServer(('', args.listen), self.oscDispatcher)

		self.client = udp_client.SimpleUDPClient(args.ip, args.port)
		self.client.send_message("/Connect", args.listen)

		self.linesClearedCallbacks = []
		self.lineChangedCallbacks = []
		self.paramNameChangedCallbacks = []
		self.paramValueChangedCallbacks = []
		self.paramCtrlChangedCallbacks = []

		self.lineChangedNotificationsEnabled = True
		self.timer = None
		self.linesSnapshot = None

	def navigationActivate(self):
		self.client.send_message("/NavActivate", 1.0)

	def navigationNext(self):
		self.client.send_message("/NavNext", 1.0)

	def navigationPrevious(self):
		self.client.send_message("/NavPrev", 1.0)

	def clearParams(self):
		self.params = [{"name": "", "value": "", "ctrl": 0.0} for _ in range(Orac.MAX_PARAMS)]
		for i in range(Orac.MAX_PARAMS):
			self.notifyParamNameChanged(i, "")
			self.notifyParamValueChanged(i, "")
			self.notifyParamCtrlChanged(i, 0.0)

	def moduleNext(self):
		self.clearParams()
		self.client.send_message("/ModuleNext", 1.0)

	def modulePrevious(self):
		self.clearParams()
		self.client.send_message("/ModulePrev", 1.0)

	def paramSet(self, param, value):
		value = max(min(value, 1.0), 0.0)
		self.client.send_message("/P%dCtrl" % (param+1), value)
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
		self.server.serve_forever()

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
		self.timer = None

	def clearTextHandler(self, address, *osc_arguments):
		self.lineChangedNotificationsEnabled = False

		if self.timer != None:
			self.timer.cancel()
		else:
			self.linesSnapshot = self.lines.copy()

		self.timer = Timer(0.2, self.handleScreenUpdate)
		self.timer.start()

		self.lines = [""]*Orac.MAX_LINES

	@staticmethod
	def decodeParamId(oscAddress):
		return ord(oscAddress[2]) - ord('1')

	def paramDescHandler(self, address, *osc_arguments):
		i = Orac.decodeParamId(address)
		if self.params[i]["name"] != osc_arguments[0]:
			self.params[i]["name"] = osc_arguments[0]
			self.notifyParamNameChanged(i, osc_arguments[0])

	def paramValueHandler(self, address, *osc_arguments):
		i = Orac.decodeParamId(address)
		if self.params[i]["value"] != osc_arguments[0]:
			self.params[i]["value"] = osc_arguments[0]
			self.notifyParamValueChanged(i, osc_arguments[0])

	def paramCtrlHandler(self, address, *osc_arguments):
		i = Orac.decodeParamId(address)
		if self.params[i]["ctrl"] != osc_arguments[0]:
			self.params[i]["ctrl"] = osc_arguments[0]
			self.notifyParamCtrlChanged(i, osc_arguments[0])

	def allOtherHandler(self, address, *osc_arguments):
		print(address, osc_arguments)

# Class for interfacing with Midiboy
class OracCtl:
	class Button(IntEnum):
		B     = 0
		A     = 1
		Right = 2
		Down  = 3
		Left  = 4
		Up    = 5

	@staticmethod
	def findOracCtlPort(port):
		available_ports = port.get_ports()
		i = 0
		for p in available_ports:
			if "ORAC-CTL" in p:
				return i
			i = i+1

		raise Exception('ORAC-CTL port not found!')

	def __init__(self):
		self.midiOut = rtmidi.MidiOut()
		self.midiIn = rtmidi.MidiIn()

		self.midiOut.open_port(OracCtl.findOracCtlPort(self.midiOut))
		self.midiIn.open_port(OracCtl.findOracCtlPort(self.midiIn))
		self.midiIn.set_callback(self.midiInCallback)

		self.inputCallbacks = []

	def __del__(self):
		self.midiOut.close_port()
		del self.midiOut
		self.midiIn.close_port()
		del self.midiIn

	def addInputCallback(self, callback):
		self.inputCallbacks.append(callback)

	def notifyInput(self, button, down):
		for c in self.inputCallbacks:
			c(self, button, down)

	def midiInCallback(self, event, data=None):
		message = event[0]

		if len(message) != 3 or message[0] != 0xf0 or message[1] & 0x3f >= 6 or message[2] != 0xf7:
			print("Ignoring unexpected message:", message)
			return

		down = (message[1] & 0x40) != 0
		self.notifyInput(OracCtl.Button(message[1] & 0x3f), down)

	def printLine(self, line, text, inverted):
		msg = [0xf0, 0x40 if inverted else 0x00, line]

		for c in bytes(text if text else "", encoding='utf-8'):
			msg.append(c if c <= 0x7f else '_')

		msg.append(0xf7)

		self.midiOut.send_message(msg)

	def printParam(self, i, name, value, inverted):
		if not name or not value:
			self.printLine(i, "", inverted)
		else:
			self.printLine(i, "%s: %s" % (name, value), inverted)

	def printCtrl(self, i, ctrl, inverted):
		msg = [0xf0, 0x41 if inverted else 0x01, i, int(ctrl * 127), 0xf7]
		self.midiOut.send_message(msg)

	def clearScreen(self):
		msg = [0xf0, 0x02, 0xf7]
		self.midiOut.send_message(msg)

	def setViewMode(self, mode):
		msg = [0xf0, 0x03, int(mode), 0xf7]
		self.midiOut.send_message(msg)

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
			for i in range(Orac.MAX_PARAMS):
				if self.isParamDefined(i):
					paramFound = True
					self.oracCtl.printParam(i, self.params[i]["name"], self.params[i]["value"], i == self.selectedParam)
					self.oracCtl.printCtrl(i, self.params[i]["ctrl"], i == self.selectedParam)
			if not paramFound:
				self.oracCtl.printLine(0, "This module has no params!", False)

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
			self.oracCtl.printParam(i, self.params[i]["name"], self.params[i]["value"], i == self.selectedParam)

	def onParamValueChanged(self, sender, i, value):
		self.params[i]["value"] = value
		if self.mode == Controller.Mode.PARAMS:
			self.oracCtl.printParam(i, self.params[i]["name"], self.params[i]["value"], i == self.selectedParam)

	def onParamCtrlChanged(self, sender, i, ctrl):
		self.params[i]["ctrl"] = ctrl
		if self.mode == Controller.Mode.PARAMS:
			self.oracCtl.printCtrl(i, self.params[i]["ctrl"], i == self.selectedParam)

	def selectNextParam(self):
		prev = self.selectedParam
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
		# Make a dummy change so this param can be mapped.
		orac.paramSet(param, self.params[param]["ctrl"] + 0.00001)
		orac.paramSet(param, self.params[param]["ctrl"] - 0.00001)
		orac.paramSet(param, self.params[param]["ctrl"])

	def onButtonEvent(self, sender, button, down):
		if not down:
			return

		if button == OracCtl.Button.B:
			self.setMode(Controller.Mode.MENU if self.mode == Controller.Mode.PARAMS else Controller.Mode.PARAMS)
			return

		if self.mode == Controller.Mode.MENU:
			if button == OracCtl.Button.A:
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
				self.activateParam(self.selectedParam)
			elif button == OracCtl.Button.Up:
				self.selectPrevParam()
				self.activateParam(self.selectedParam)
			elif button == OracCtl.Button.Right:
				self.increaseParam(self.selectedParam)
			elif button == OracCtl.Button.Left:
				self.decreaseParam(self.selectedParam)
			elif button == OracCtl.Button.A:
				self.activateParam(self.selectedParam)

orac = Orac(args.ip, args.port)
oracCtl = OracCtl()
ctrl = Controller(orac, oracCtl)

try:
	orac.run()
finally:
	del ctrl
	del oracCtl
	orac.shutdown()
	del orac
	print("Done!")
