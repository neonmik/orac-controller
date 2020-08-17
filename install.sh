#!/bin/sh

if [ ! $(id -u) = "0" ]; then
	echo "Please run using 'sudo ./install.sh'"
	exit 1
fi

BASE_PATH=$(dirname $(readlink -f $0))

apt install python3-pip python3-pil libjack-jackd2-dev
pip3 install python-osc adafruit-circuitpython-ssd1306

install -v -m 644 $BASE_PATH/orac-bonnet-bridge/99-orac-bonnet-bridge.rules /etc/udev/rules.d/
install -v -m 644 $BASE_PATH/orac-bonnet-bridge/orac-bonnet-bridge.service /usr/lib/systemd/system/
install -v -m 755 $BASE_PATH/orac-bonnet-bridge/OracBonnetBridge.py /usr/local/bin/
install -v -m 755 $BASE_PATH/orac-bonnet-bridge/pixel_arial_11.ttf /usr/local/bin/
install -v -m 755 $BASE_PATH/orac-bonnet-bridge/images/oracsplash /usr/local/bin/images/
install -v -m 755 $BASE_PATH/orac-bonnet-bridge/images/oractitle /usr/local/bin/images/
systemctl daemon-reload
udevadm control --reload
