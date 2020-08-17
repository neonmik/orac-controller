# Adafruit OLED Bonnet &lt;-> Orac UI

## Sketch and Bridge Install


Firstly, if you haven't already you need to activate the I2C interface on your Raspberry Pi.

From the command line or Terminal window start by running the following command :

```
sudo raspi-config
```

Highlight the “I2C” option and activate, follow the instructions through and reboot your Raspberry Pi.




Now, install OracBonnetBridge.py on your Raspberry Pi:

```
git clone https://github.com/neonmik/orac-controller
cd orac-controller
sudo ./install.sh
sudo halt
```

Connect the Adafruit OLED Bonnet to your Raspberry Pi and power back on, it should automatically connect to Orac and display the UI.

If it doesn't, make sure Orac and MEC are running.

**Note**: the Adafruit bonnet will only work if you **disable** the pisound button functions. You can do this in patchbox from the commandline, or via ssh.

I don't have a pisound, so I'm not sure on the compatability, but I'm aware one of the buttons on this controller fires the pisound button funtions.

## Controls

On the menu screen:

* Up and Down - move between the lines.
* Left and Right - move between the modules.
* A (#6) - activate the selected item.
* B (#5)- go to the parameters screen.

On the parameters screen:

* Up and Down - move between the parameters.
* Left and Right:
    * If a param is activated, decrease and increase its value respectively.
    * Otherwise go to previous or next parameter page.
* A - activate the currently selected parameter for changing the value. If MIDI Learn is enabled, after the parameters' value is changed using Left or Right, the parameter can be MIDI mapped by moving a control on a MIDI controller.
* B goes to the menu screen.
