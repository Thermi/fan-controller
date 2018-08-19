#! /bin/python3 -Bi


import subprocess

blockDeviceName="sda"
proc = subprocess.run(["/usr/bin/smartctl", "-a","/dev/{}".format(blockDeviceName)], stdout=subprocess.PIPE)

for line in proc.stdout.splitlines():
	if b'Temperature_Celsius' in line:
		return int(str(line.split()[-1].split(b'(')[0]), "utf-8")
return None
