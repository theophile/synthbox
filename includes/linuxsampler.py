import os
import re
import logging
import socket
from time import sleep
from os.path import isdir
from subprocess import check_output
from collections import OrderedDict
import pexpect


class lscp_error(Exception):
    pass


class lscp_warning(Exception):
    pass


class linuxsampler:

    # ---------------------------------------------------------------------------
    # Config variables
    # ---------------------------------------------------------------------------

    lscp_port = 8888
    lscp_v1_6_supported = False

    # ---------------------------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------------------------

    def __init__(self, controller_id=0):
        self.name = "LinuxSampler"
        self.nickname = "LS"
        self.jackname = "LinuxSampler"
        self.controller_id = controller_id

        self.sampleDirs = ["/home/pi/soundfonts/sfz", "/home/pi/soundfonts/gig"]

        self.sampleList = {}
        self.samplePath = self.buildSampleList()
        self.patchList = {}
        self.effectList = {}

        self.sock = None
        self.proc = None
        self.proc_timeout = 20
        self.proc_start_sleep = None
        self.command = "linuxsampler --lscp-port {}".format(self.lscp_port)
        self.command_env = None
        self.command_prompt = "\nLinuxSampler initialization completed."

        self.ls_chan_info = {}
        self.ls_midi_device_id = None
        self.ls_audio_device_id = None

        self.start()
        # self.lscp_connect()
        # self.lscp_get_version()
        # self.reset()
        # self.buildPatchList()
        self.buildEffectList()

    def reset(self):
        self.ls_chan_info = {}
        self.ls_init()

    # ---------------------------------------------------------------------------
    # Subproccess Management & IPC
    # ---------------------------------------------------------------------------
    def start(self):
        if self.proc:
            return

        logging.info("Starting Engine {}".format(self.name))
        logging.debug("Command: {}".format(self.command))
        if self.command_env:
            self.proc = pexpect.spawn(
                self.command, timeout=self.proc_timeout, env=self.command_env
            )
        else:
            self.proc = pexpect.spawn(self.command, timeout=self.proc_timeout)
        self.proc.delaybeforesend = 0
        output = self.proc_get_output()
        if self.proc_start_sleep:
            sleep(self.proc_start_sleep)
        self.lscp_connect()
        self.lscp_get_version()
        # self.reset()
        return output

    def stop(self):
        if self.proc:
            logging.info("Stoping Engine " + self.name)
            self.proc.terminate()
            sleep(0.2)
            self.proc.terminate(True)
            self.proc = None

    def proc_get_output(self):
        if self.command_prompt:
            self.proc.expect(self.command_prompt)
            return self.proc.before.decode()
        else:
            logging.warning("Command Prompt is not defined!")
            return None

    def proc_cmd(self, cmd):
        if self.proc:
            # logging.debug("proc command: "+cmd)
            self.proc.sendline(cmd)
            # logging.debug("proc output:\n{}".format(out))
            return self.proc_get_output()

    def lscp_connect(self):
        logging.info("Connecting with LinuxSampler Server...")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(0)
        self.sock.settimeout(1)
        i = 0
        while i < 20:
            try:
                self.sock.connect(("127.0.0.1", self.lscp_port))
                break
            except:
                sleep(0.25)
                i += 1
        return self.sock

    def lscp_get_version(self):
        sv_info = self.lscp_send_multi("GET SERVER INFO")
        if "PROTOCOL_VERSION" in sv_info:
            match = re.match(
                r"(?P<major>\d+)\.(?P<minor>\d+).*", sv_info["PROTOCOL_VERSION"]
            )
            if match:
                version_major = int(match["major"])
                version_minor = int(match["minor"])
                if version_major > 1 or (version_major == 1 and version_minor >= 6):
                    self.lscp_v1_6_supported = True

    def lscp_send(self, data):
        command = command + "\r\n"
        self.sock.send(data.encode())

    def lscp_get_result_index(self, result):
        parts = result.split("[")
        if len(parts) > 1:
            parts = parts[1].split("]")
            return int(parts[0])

    def lscp_send_single(self, command):
        # logging.debug("LSCP SEND => %s" % command)
        command = command + "\r\n"
        try:
            self.sock.send(command.encode())
            line = self.sock.recv(4096)
        except Exception as err:
            logging.error("FAILED lscp_send_single(%s): %s" % (command, err))
            return None
        line = line.decode()
        # print(line)
        # logging.debug("LSCP RECEIVE => %s" % line)
        if line[0:2] == "OK":
            result = self.lscp_get_result_index(line)
            # print('result is: {}'.format(result))
        elif line[0:3] not in ["ERR", "WRN"]:
            result = line.splitlines()[0]
        elif line[0:3] == "ERR":
            parts = line.split(":")
            # print('Error: line[0:3]=="ERR"')
            # print(line)
            raise lscp_error("{} ({} {})".format(parts[2], parts[0], parts[1]))
        else:
            parts = line.split(":")
            # print('Error: line[0:3]=="WRN"')
            # print(line)
            raise lscp_warning("{} ({} {})".format(parts[2], parts[0], parts[1]))
        return result

    def lscp_send_multi(self, command, sep=":"):
        # logging.debug("LSCP SEND => %s" % command)
        command = command + "\r\n"
        try:
            self.sock.send(command.encode())
            result = self.sock.recv(4096)
        except Exception as err:
            logging.error("FAILED lscp_send_multi(%s): %s" % (command, err))
            return None
        lines = result.decode().split("\r\n")
        result = OrderedDict()
        for line in lines:
            # logging.debug("LSCP RECEIVE => %s" % line)
            if line[0:2] == "OK":
                result = self.lscp_get_result_index(line)
            elif line[0:3] == "ERR":
                parts = line.split(":")
                # print('Error: line[0:3]=="ERR"')
                # print(line)
                raise lscp_error("{} ({} {})".format(parts[2], parts[0], parts[1]))
            elif line[0:3] == "WRN":
                parts = line.split(":")
                # print('Error: line[0:3]=="WRN"')
                # print(line)
                raise lscp_warning("{} ({} {})" % (parts[2], parts[0], parts[1]))
            elif len(line) > 3:
                parts = line.split(sep)
                result[parts[0]] = parts[1]
        return result

    # ---------------------------------------------------------------------------
    # MIDI Channel Management
    # ---------------------------------------------------------------------------

    def set_midi_chan(self):
        if self.ls_chan_info:
            ls_chan_id = self.ls_chan_info["chan_id"]
            self.lscp_send_single(
                "SET CHANNEL MIDI_INPUT_CHANNEL {} {}".format(ls_chan_id, 0)
            )

    # ---------------------------------------------------------------------------
    # Bank Management
    # ---------------------------------------------------------------------------

    def get_bank_list(self):
        return self.get_dirlist(self.bank_dirs)

    def set_bank(self, bank):
        return True

    def buildSampleList(self):
        for dir in self.sampleDirs:
            for file in [
                os.path.join(dp, f) for dp, dn, fn in os.walk(dir) for f in fn
            ]:
                if file[-4:].lower() in [".sfz", ".gig"]:
                    name = os.path.splitext(os.path.basename(file))[0]
                    self.sampleList.update({name: file})
        return self.sampleList[list(self.sampleList.keys())[0]]

    def get_instrument_list(self, path):
        result = self.lscp_send_single("LIST FILE INSTRUMENTS '{}'".format(path))
        return result.split(",")

    def get_instrument_info(self, path, inst):
        command = "GET FILE INSTRUMENT INFO '{}' {}".format(path, inst)
        command = command + "\r\n"
        try:
            self.sock.send(command.encode())
            result = self.sock.recv(4096)
        except Exception as err:
            logging.error("FAILED get_instrument_info(%s): %s" % (command, err))
            return None
        lines = result.decode().split("\r\n")
        result = {}
        for line in lines:
            if line[0:2] == "OK":
                parts = line.split("[")
                if len(parts) > 1:
                    parts = parts[1].split("]")
                result = int(parts[0])
            elif line[0:3] == "ERR":
                parts = line.split(":")
                raise lscp_error("{} ({} {})".format(parts[2], parts[0], parts[1]))
            elif line[0:3] == "WRN":
                parts = line.split(":")
                raise lscp_warning("{} ({} {})" % (parts[2], parts[0], parts[1]))
            elif len(line) > 3:
                parts = line.split(": ")
                result[parts[0].lower()] = parts[1]
        result["inst_id"] = inst
        result["path"] = path
        return result

    def buildPatchList(self, path: str):
        self.BankPatchList = []
        for inst in self.get_instrument_list(path):
            dict = self.get_instrument_info(path, inst)
            self.BankPatchList.append(
                [int(dict["inst_id"]), dict["name"], dict["format_family"]]
            )
        return self.BankPatchList

    def buildEffectList(self):
        self.effectList = {}
        effects = self.lscp_send_single("LIST AVAILABLE_EFFECTS").split(",")
        for effect_id in effects:
            effect_info = self.lscp_send_multi("GET EFFECT INFO {}".format(effect_id))
            name = effect_info["NAME"].lstrip()
            desc = effect_info["DESCRIPTION"].lstrip()
            system = effect_info["SYSTEM"].lstrip()
            module = effect_info["MODULE"].lstrip()
            dict = {
                "effect_id": effect_id,
                "description": desc,
                "system": system,
                "module": module,
            }
            self.effectList[name] = dict
        return self.effectList

    # ---------------------------------------------------------------------------
    # Preset Management
    # ---------------------------------------------------------------------------

    @staticmethod
    def _get_preset_list(bank):
        logging.info("Getting Preset List for %s" % bank[2])
        preset_list = []
        preset_dpath = bank[0]
        if os.path.isdir(preset_dpath):
            exclude_sfz = re.compile(r"[MOPRSTV][1-9]?l?\.sfz")
            cmd = "find '" + preset_dpath + "' -maxdepth 3 -type f -name '*.sfz'"
            output = check_output(cmd, shell=True).decode("utf8")
            cmd = "find '" + preset_dpath + "' -maxdepth 2 -type f -name '*.gig'"
            output = output + "\n" + check_output(cmd, shell=True).decode("utf8")
            lines = output.split("\n")
            i = 0
            for f in lines:
                if f:
                    filehead, filetail = os.path.split(f)
                    if not exclude_sfz.fullmatch(filetail):
                        filename, filext = os.path.splitext(f)
                        filename = filename[len(preset_dpath) + 1 :]
                        title = filename.replace("_", " ")
                        engine = filext[1:].lower()
                        preset_list.append(
                            [f, i, title, engine, "{}.{}".format(filename, filext)]
                        )
                        i += 1
        return preset_list

    def get_preset_list(self, bank):
        return self._get_preset_list(bank)

    def set_preset(self, preset, preload=False):
        return bool(self.ls_set_preset(preset[3], preset[0]))

    def cmp_presets(self, preset1, preset2):
        try:
            return preset1[0] == preset2[0] and preset1[3] == preset2[3]
        except:
            return False

    # ---------------------------------------------------------------------------
    # Controllers Management
    # ---------------------------------------------------------------------------

    # ---------------------------------------------------------------------------
    # Specific functions
    # ---------------------------------------------------------------------------

    def ls_init(self):
        # Reset
        self.lscp_send_single("RESET")

        # Config Audio ALSA Device
        self.ls_audio_device_id = self.lscp_send_single(
            "CREATE AUDIO_OUTPUT_DEVICE JACK ACTIVE='true' CHANNELS='16' NAME='{}'".format(
                self.jackname
            )
        )
        for i in range(8):
            self.lscp_send_single(
                "SET AUDIO_OUTPUT_CHANNEL_PARAMETER {} {} NAME='CH{}_1'".format(
                    self.ls_audio_device_id, i * 2, i
                )
            )
            self.lscp_send_single(
                "SET AUDIO_OUTPUT_CHANNEL_PARAMETER {} {} NAME='CH{}_2'".format(
                    self.ls_audio_device_id, i * 2 + 1, i
                )
            )

        # Config MIDI JACK Device 1
        self.ls_midi_device_id = self.lscp_send_single(
            "CREATE MIDI_INPUT_DEVICE JACK ACTIVE='true' NAME='LinuxSampler' PORTS='1'"
        )

        # Global volume level
        self.lscp_send_single("SET VOLUME 0.75")
        self.set_midi_chan()

    def release(self):
        if self.ls_chan_info:
            self.lscp_send_single(
                "REMOVE CHANNEL {}".format(self.ls_chan_info["chan_id"])
            )
            self.ls_chan_info = {}
        if self.ls_midi_device_id is not None:
            self.lscp_send_single(
                "DESTROY MIDI_INPUT_DEVICE {}".format(self.ls_midi_device_id)
            )
            self.ls_midi_device_id = None
        if self.ls_audio_device_id is not None:
            self.lscp_send_single(
                "DESTROY AUDIO_OUTPUT_DEVICE {}".format(self.ls_audio_device_id)
            )
            self.ls_audio_device_id = None

    def switchSample(self, path: str, inst_id=0):
        if not self.ls_chan_info:
            self.reset()
            ls_chan_id = self.ls_set_channel()
        else:
            ls_chan_id = self.ls_chan_info["chan_id"]
        self.BankPatchList = self.buildPatchList(path)
        sampleinfo = self.BankPatchList[inst_id]
        format_family = sampleinfo[2].lower()
        if self.ls_chan_info["ls_engine"] != format_family:
            self.lscp_send_single("LOAD ENGINE {} {}".format(format_family, ls_chan_id))
            self.ls_chan_info["ls_engine"] = format_family
        self.sock.settimeout(10)
        self.lscp_send_single(
            "LOAD INSTRUMENT '{}' {} {}".format(path, inst_id, ls_chan_id)
        )
        self.sock.settimeout(1)
        self.samplePath = path
        self.Patch = inst_id
        self.PatchName = sampleinfo[1]
        self.Index = self.BankPatchList.index(sampleinfo)
        return

    def nextPatch(self, direction):
        """
        Finds next non empty patch, moving to the next bank if needs be.
        Max bank 128 before it loops around to 0.
        """
        if direction == "up":
            if (self.Index + 1) == len(self.BankPatchList):
                self.Index = 0
            else:
                self.Index += 1
        if direction == "down":
            if self.Index == 0:
                self.Index = len(self.BankPatchList) - 1
            else:
                self.Index -= 1
        print(self.BankPatchList[self.Index][1])
        print(self.Index)
        self.switchSample(self.samplePath, self.Index)
        return

    def ls_set_channel(self):
        # Adding new channel
        self.sock.settimeout(10)
        ls_chan_id = self.lscp_send_single("ADD CHANNEL")
        if ls_chan_id >= 0:
            self.lscp_send_single(
                "SET CHANNEL AUDIO_OUTPUT_DEVICE {} {}".format(
                    ls_chan_id, self.ls_audio_device_id
                )
            )

            # Configure MIDI input
            if self.lscp_v1_6_supported:
                self.lscp_send_single(
                    "ADD CHANNEL MIDI_INPUT {} {} 0".format(
                        ls_chan_id, self.ls_midi_device_id
                    )
                )
            else:
                self.lscp_send_single(
                    "SET CHANNEL MIDI_INPUT_DEVICE {} {}".format(
                        ls_chan_id, self.ls_midi_device_id
                    )
                )
                self.lscp_send_single(
                    "SET CHANNEL MIDI_INPUT_PORT {} {}".format(ls_chan_id, 0)
                )
            self.ls_chan_info = {
                "chan_id": ls_chan_id,
                "ls_engine": None,
                "audio_output": None,
            }
            return ls_chan_id

    def ls_set_preset(self, ls_engine, fpath):
        res = False
        if self.ls_chan_info:
            ls_chan_id = self.ls_chan_info["chan_id"]

            # Load engine and set output channels if needed
            if ls_engine != self.ls_chan_info["ls_engine"]:
                self.lscp_send_single("LOAD ENGINE {} {}".format(ls_engine, ls_chan_id))
                self.ls_chan_info["ls_engine"] = ls_engine

                i = self.ls_get_free_output_channel()
                self.lscp_send_single(
                    "SET CHANNEL AUDIO_OUTPUT_CHANNEL {} 0 {}".format(ls_chan_id, i * 2)
                )
                self.lscp_send_single(
                    "SET CHANNEL AUDIO_OUTPUT_CHANNEL {} 1 {}".format(
                        ls_chan_id, i * 2 + 1
                    )
                )
                self.ls_chan_info["audio_output"] = i

                self.jackname = "{}:CH{}_".format(self.jackname, i)

            # Load instument
            self.sock.settimeout(10)
            self.lscp_send_single("LOAD INSTRUMENT '{}' 0 {}".format(fpath, ls_chan_id))
            res = True

        self.sock.settimeout(1)

        return res

    def ls_unset_channel(self):
        if self.ls_chan_info:
            chan_id = self.ls_chan_info["chan_id"]
            self.lscp_send_single("RESET CHANNEL {}".format(chan_id))

            # Remove sampler channel
            self.lscp_send_single("REMOVE CHANNEL MIDI_INPUT {}".format(chan_id))
            self.lscp_send_single("REMOVE CHANNEL {}".format(chan_id))
            self.ls_chan_info = None

    def ls_get_free_output_channel(self):
        for i in range(16):
            busy = False
            if self.ls_chan_info and i == self.ls_chan_info["audio_output"]:
                busy = True
            if not busy:
                return i
