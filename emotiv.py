import gevent

try:
    import pywinusb.hid as hid

    windows = True
except:
    windows = False

import os
from gevent.queue import Queue
from Crypto.Cipher import AES
from Crypto import Random
import time

sensorBits = {
    'F3': [10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7],
    'FC5': [28, 29, 30, 31, 16, 17, 18, 19, 20, 21, 22, 23, 8, 9],
    'AF3': [46, 47, 32, 33, 34, 35, 36, 37, 38, 39, 24, 25, 26, 27],
    'F7': [48, 49, 50, 51, 52, 53, 54, 55, 40, 41, 42, 43, 44, 45],
    'T7': [66, 67, 68, 69, 70, 71, 56, 57, 58, 59, 60, 61, 62, 63],
    'P7': [84, 85, 86, 87, 72, 73, 74, 75, 76, 77, 78, 79, 64, 65],
    'O1': [102, 103, 88, 89, 90, 91, 92, 93, 94, 95, 80, 81, 82, 83],
    'O2': [140, 141, 142, 143, 128, 129, 130, 131, 132, 133, 134, 135, 120, 121],
    'P8': [158, 159, 144, 145, 146, 147, 148, 149, 150, 151, 136, 137, 138, 139],
    'T8': [160, 161, 162, 163, 164, 165, 166, 167, 152, 153, 154, 155, 156, 157],
    'F8': [178, 179, 180, 181, 182, 183, 168, 169, 170, 171, 172, 173, 174, 175],
    'AF4': [196, 197, 198, 199, 184, 185, 186, 187, 188, 189, 190, 191, 176, 177],
    'FC6': [214, 215, 200, 201, 202, 203, 204, 205, 206, 207, 192, 193, 194, 195],
    'F4': [216, 217, 218, 219, 220, 221, 222, 223, 208, 209, 210, 211, 212, 213]
}
quality_bits = [99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112]

g_battery = 0
tasks = Queue()

# this is useful for further reverse engineering for EmotivPacket
byte_names = {
    "saltie-sdk": [  # also clamshell-v1.3-sydney
                     "INTERPOLATED",
                     "COUNTER",
                     "BATTERY",
                     "FC6",
                     "F8",
                     "T8",
                     "PO4",
                     "F4",
                     "AF4",
                     "FP2",
                     "OZ",
                     "P8",
                     "FP1",
                     "AF3",
                     "F3",
                     "P7",
                     "T7",
                     "F7",
                     "FC5",
                     "GYRO_X",
                     "GYRO_Y",
                     "RESERVED",
                     "ETE1",
                     "ETE2",
                     "ETE3",
    ],
    "clamshell-v1.3-san-francisco": [  # amadi ?
                                       "INTERPOLATED",
                                       "COUNTER",
                                       "BATTERY",
                                       "F8",
                                       "UNUSED",
                                       "AF4",
                                       "T8",
                                       "UNUSED",
                                       "T7",
                                       "F7",
                                       "F3",
                                       "F4",
                                       "P8",
                                       "PO4",
                                       "FC6",
                                       "P7",
                                       "AF3",
                                       "FC5",
                                       "OZ",
                                       "GYRO_X",
                                       "GYRO_Y",
                                       "RESERVED",
                                       "ETE1",
                                       "ETE2",
                                       "ETE3",
    ],
    "clamshell-v1.5": [
        "INTERPOLATED",
        "COUNTER",
        "BATTERY",
        "F3",
        "FC5",
        "AF3",
        "F7",
        "T7",
        "P7",
        "O1",
        "SQ_WAVE",
        "UNUSED",
        "O2",
        "P8",
        "T8",
        "F8",
        "AF4",
        "FC6",
        "F4",
        "GYRO_X",
        "GYRO_Y",
        "RESERVED",
        "ETE1",
        "ETE2",
        "ETE3",
    ],
    "clamshell-v3.0": [
        "INTERPOLATED",
        "COUNTER",
        "BATTERY",
        "F3",
        "FC5",
        "AF3",
        "F7",
        "T7",
        "P7",
        "O1",
        "SQ_WAVE",
        "UNUSED",
        "O2",
        "P8",
        "T8",
        "F8",
        "AF4",
        "FC6",
        "F4",
        "GYRO_X",
        "GYRO_Y",
        "RESERVED",
        "ETE1",
        "ETE2",
        "ETE3",
    ],
}


class EmotivPacket(object):
    def __init__(self, data, sensors):
        global g_battery
        self.rawData = data
        self.counter = ord(data[0])
        self.battery = g_battery
        if (self.counter > 127):
            self.battery = self.counter
            g_battery = self.battery_percent()
            self.counter = 128
        self.sync = self.counter == 0xe9

        # the RESERVED byte stores the least significant 4 bits for gyroX and gyroY
        self.gyroX = ((ord(data[29]) << 4) | (ord(data[31]) >> 4))
        self.gyroY = ((ord(data[30]) << 4) | (ord(data[31]) & 0x0F))
        sensors['X']['value'] = self.gyroX
        sensors['Y']['value'] = self.gyroY

        for name, bits in sensorBits.items():
            value = self.get_level(self.rawData, bits)
            setattr(self, name, (value,))
            sensors[name]['value'] = value
        self.handle_quality(sensors)
        self.sensors = sensors

    def get_level(self, data, bits):
        level = 0
        for i in range(13, -1, -1):
            level <<= 1
            b, o = (bits[i] / 8) + 1, bits[i] % 8
            level |= (ord(data[b]) >> o) & 1
        return level

    def handle_quality(self, sensors):
        current_contact_quality = self.get_level(self.rawData, quality_bits) / 540
        sensor = ord(self.rawData[0])
        if sensor == 0:
            sensors['F3']['quality'] = current_contact_quality
        elif sensor == 1:
            sensors['FC5']['quality'] = current_contact_quality
        elif sensor == 2:
            sensors['AF3']['quality'] = current_contact_quality
        elif sensor == 3:
            sensors['F7']['quality'] = current_contact_quality
        elif sensor == 4:
            sensors['T7']['quality'] = current_contact_quality
        elif sensor == 5:
            sensors['P7']['quality'] = current_contact_quality
        elif sensor == 6:
            sensors['O1']['quality'] = current_contact_quality
        elif sensor == 7:
            sensors['O2']['quality'] = current_contact_quality
        elif sensor == 8:
            sensors['P8']['quality'] = current_contact_quality
        elif sensor == 9:
            sensors['T8']['quality'] = current_contact_quality
        elif sensor == 10:
            sensors['F8']['quality'] = current_contact_quality
        elif sensor == 11:
            sensors['AF4']['quality'] = current_contact_quality
        elif sensor == 12:
            sensors['FC6']['quality'] = current_contact_quality
        elif sensor == 13:
            sensors['F4']['quality'] = current_contact_quality
        elif sensor == 14:
            sensors['F8']['quality'] = current_contact_quality
        elif sensor == 15:
            sensors['AF4']['quality'] = current_contact_quality
        elif sensor == 64:
            sensors['F3']['quality'] = current_contact_quality
        elif sensor == 65:
            sensors['FC5']['quality'] = current_contact_quality
        elif sensor == 66:
            sensors['AF3']['quality'] = current_contact_quality
        elif sensor == 67:
            sensors['F7']['quality'] = current_contact_quality
        elif sensor == 68:
            sensors['T7']['quality'] = current_contact_quality
        elif sensor == 69:
            sensors['P7']['quality'] = current_contact_quality
        elif sensor == 70:
            sensors['O1']['quality'] = current_contact_quality
        elif sensor == 71:
            sensors['O2']['quality'] = current_contact_quality
        elif sensor == 72:
            sensors['P8']['quality'] = current_contact_quality
        elif sensor == 73:
            sensors['T8']['quality'] = current_contact_quality
        elif sensor == 74:
            sensors['F8']['quality'] = current_contact_quality
        elif sensor == 75:
            sensors['AF4']['quality'] = current_contact_quality
        elif sensor == 76:
            sensors['FC6']['quality'] = current_contact_quality
        elif sensor == 77:
            sensors['F4']['quality'] = current_contact_quality
        elif sensor == 78:
            sensors['F8']['quality'] = current_contact_quality
        elif sensor == 79:
            sensors['AF4']['quality'] = current_contact_quality
        elif sensor == 80:
            sensors['FC6']['quality'] = current_contact_quality
        else:
            sensors['Unknown']['quality'] = current_contact_quality
            sensors['Unknown']['value'] = sensor
        return current_contact_quality

    def battery_percent(self):
        if self.battery > 248:
            return 100
        elif self.battery == 247:
            return 99
        elif self.battery == 246:
            return 97
        elif self.battery == 245:
            return 93
        elif self.battery == 244:
            return 89
        elif self.battery == 243:
            return 85
        elif self.battery == 242:
            return 82
        elif self.battery == 241:
            return 77
        elif self.battery == 240:
            return 72
        elif self.battery == 239:
            return 66
        elif self.battery == 238:
            return 62
        elif self.battery == 237:
            return 55
        elif self.battery == 236:
            return 46
        elif self.battery == 235:
            return 32
        elif self.battery == 234:
            return 20
        elif self.battery == 233:
            return 12
        elif self.battery == 232:
            return 6
        elif self.battery == 231:
            return 4
        elif self.battery == 230:
            return 3
        elif self.battery == 229:
            return 2
        elif self.battery == 228:
            return 2
        elif self.battery == 227:
            return 2
        elif self.battery == 226:
            return 1
        else:
            return 0

    def __repr__(self):
        return 'EmotivPacket(counter=%i, battery=%i, gyroX=%i, gyroY=%i, F3=%i)' % (
            self.counter,
            self.battery,
            self.gyroX,
            self.gyroY,
            self.F3[0],
        )


class Emotiv(object):
    def __init__(self, displayOutput=False, headsetId=0, research_headset=True):
        self._goOn = True
        self.packets = Queue()
        self.packetsReceived = 0
        self.packetsProcessed = 0
        self.battery = 0
        self.displayOutput = displayOutput
        self.headsetId = headsetId
        self.research_headset = research_headset
        self.sensors = {
            'F3': {'value': 0, 'quality': 0},
            'FC6': {'value': 0, 'quality': 0},
            'P7': {'value': 0, 'quality': 0},
            'T8': {'value': 0, 'quality': 0},
            'F7': {'value': 0, 'quality': 0},
            'F8': {'value': 0, 'quality': 0},
            'T7': {'value': 0, 'quality': 0},
            'P8': {'value': 0, 'quality': 0},
            'AF4': {'value': 0, 'quality': 0},
            'F4': {'value': 0, 'quality': 0},
            'AF3': {'value': 0, 'quality': 0},
            'O2': {'value': 0, 'quality': 0},
            'O1': {'value': 0, 'quality': 0},
            'FC5': {'value': 0, 'quality': 0},
            'X': {'value': 0, 'quality': 0},
            'Y': {'value': 0, 'quality': 0},
            'Unknown': {'value': 0, 'quality': 0}
        }

    def updateStdout(self):
        while self._goOn:
            if self.displayOutput:
                if windows:
                    os.system('cls')
                else:
                    os.system('clear')
                print "Packets Received: %s Packets Processed: %s" % (self.packetsReceived, self.packetsProcessed)
                print('\n'.join(
                    "%s Reading: %s Strength: %s" % (k[1], self.sensors[k[1]]['value'], self.sensors[k[1]]['quality'])
                    for k in enumerate(self.sensors)))
                print "Battery: %i" % g_battery

    def setupWin(self):
        devices = []
        temp_data = []
        try:
            for device in hid.find_all_hid_devices():
                if device.vendor_id != 0x21A1 and device.vendor_id != 0x1234:
                    continue
                elif device.product_name == 'Emotiv RAW DATA':
                    devices.append(device)
                    device.open()
                    self.serialNum = device.serial_number
                    # print device.serial_number
                    device.set_raw_data_handler(self.handler)
            temp_data = self.setupCrypto(self.serialNum)
        finally:
            for device in devices:
                device.close()
            return temp_data

    def handler(self, data):
        assert data[0] == 0
        tasks.put_nowait(''.join(map(chr, data[1:])))
        self.packetsReceived += 1
        return True

    def setupCrypto(self, sn):
        k = ['\0'] * 16
        k[0] = sn[-1]
        k[1] = '\0'
        k[2] = sn[-2]
        k[3] = 'T'
        k[4] = sn[-3]
        k[5] = '\x10'
        k[6] = sn[-4]
        k[7] = 'B'
        k[8] = sn[-1]
        k[9] = '\0'
        k[10] = sn[-2]
        k[11] = 'H'
        k[12] = sn[-3]
        k[13] = '\0'
        k[14] = sn[-4]
        k[15] = 'P'
        key = ''.join(k)
        # print key
        iv = Random.new().read(AES.block_size)
        cipher = AES.new(key, AES.MODE_ECB, iv)
        vector = [0 for i in range(17)]
        i = 0
        while self._goOn:
            while not tasks.empty():
                if i == 10:
                    result = []
                    for bit in vector:
                        result.append(bit/10)
                    return result
                task = tasks.get()
                data = cipher.decrypt(task[:16]) + cipher.decrypt(task[16:])
                self.lastPacket = EmotivPacket(data, self.sensors)
                self.packets.put_nowait(self.lastPacket)
                self.packetsProcessed += 1
                self.displayOutput = True
                #self.updateStdout()
                self.displayOutput = False
                for k in enumerate(self.sensors):
                    vector[k[0]] += self.sensors[k[1]]['value']
                i += 1
                #print vector
                time.sleep(1)
                # edit time step here

    def dequeue(self):
        try:
            return self.packets.get()
        except Exception, e:
            print e

if __name__ == "__main__":
    try:
        a = Emotiv()
        a.setupWin()
        #temp_data = a.setupWin()
    except KeyboardInterrupt:
        a.device.close()
        gevent.shutdown()

