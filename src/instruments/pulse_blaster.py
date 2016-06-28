from src.core import Instrument, Parameter
from collections import namedtuple
import numpy as np
import itertools
import ctypes
import datetime, time

Pulse = namedtuple('Pulse', ('channel_id', 'start_time', 'duration'))
PBStateChange = namedtuple('PBStateChange', ('channel_bits', 'time'))
PBCommand = namedtuple('PBCommand', ('channel_bits', 'duration', 'command', 'command_arg'))


class PulseBlaster(Instrument):

    _PROBES = {}

    _DEFAULT_SETTINGS = Parameter([
        Parameter('output_0', [
            Parameter('channel', 0, int, 'channel to which laser is connected'),
            Parameter('status', False, bool, 'True if voltage is high to the laser, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and laser switch on [ns]')
        ]),
        Parameter('output_1', [
            Parameter('channel', 1, int, 'channel to which the daq is connected to'),
            Parameter('status', True, bool, 'True if voltage is high to the daq, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and daq acknowledgement [ns]')
        ]),
        Parameter('output_2', [
            Parameter('channel', 2, int, 'channel to which the the microwave p trigger is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the microwave p trigger, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and microwave p trigger [ns]')
        ]),
        Parameter('output_3', [
            Parameter('channel', 3, int, 'channel to which the the microwave q trigger is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the microwave q trigger, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and microwave q trigger [ns]')
        ]),
        Parameter('output_4', [
            Parameter('channel', 4, int, 'channel to which the microwave switch is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the microwave switch, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and microwave switch [ns]')
        ]),
        Parameter('clock_speed', 100, [100, 400], 'Clock speed of the pulse blaster [MHz]')
    ])

    PULSE_PROGRAM = ctypes.c_int(0)
    LONG_DELAY_THRESHOLD = 640
    MIN_DURATION = 15

    PB_INSTRUCTIONS = {
        'CONTINUE': ctypes.c_int(0),
        'STOP': ctypes.c_int(1),
        'LOOP': ctypes.c_int(2),
        'END_LOOP': ctypes.c_int(3),
        'BRANCH': ctypes.c_int(6),
        'LONG_DELAY': ctypes.c_int(7)
    }

    def __init__(self, name = None, settings = None):
        super(PulseBlaster, self).__init__(name, settings)
        self.pb = ctypes.windll.LoadLibrary('C:\\Windows\\System32\\spinapi64.dll')
        self.update(self._DEFAULT_SETTINGS)
        self.estimated_runtime = None
        self.sequence_start_time = None


    def update(self, settings):
        # call the update_parameter_list to update the parameter list
        super(PulseBlaster, self).update(settings)

        for key, value in settings.iteritems():
            if isinstance(value, dict) and 'status' in value.keys():
                self.pb.pb_reset()
                assert self.pb.pb_init() == 0, 'Could not initialize the pulseblsater on pb_init() command.'
                self.pb.pb_core_clock(ctypes.c_double(self.settings['clock_speed']))
                self.pb.pb_start_programming(self.PULSE_PROGRAM)
                self.pb.pb_inst_pbonly(ctypes.c_int(self.settings2bits() | 0xE00000), self.PB_INSTRUCTIONS['BRANCH'],
                                             ctypes.c_int(0), ctypes.c_double(100))
                self.pb.pb_stop_programming()
                self.pb.pb_start()
                assert self.pb.pb_read_status() & 0b100 == 0b100, 'pulseblaster did not begin running after start() called.'
                self.pb.pb_stop()
                self.pb.pb_close()
                break


    def settings2bits(self):
        bits = 0
        for output, output_params in self.settings.iteritems():
            if isinstance(output_params, dict) and 'channel' in output_params and 'status' in output_params:
                if output_params['status']:
                    bits |= 1 << output_params['channel']

        return bits

    def get_delay(self, channel_id):
        """
        Gets the delay for an inputted channel id, a name or number.
        Args:
            channel_id: channel for which you want the delay. Must be an integer or string

        Returns:
            the delay, in ns, for a given channel id

        """
        if isinstance(channel_id, str):
            channel_name = channel_id
            return self.settings[channel_name]['delay_time']

        elif isinstance(channel_id, int):
            channel_num = channel_id
            for key, value in self.settings:
                if isinstance(value, dict) and 'channel' in value.keys() and value['channel'] == channel_num:
                    return self.settings[key]['delay_time']

        raise AttributeError('Could not find delay of channel name or number: {s}'.format(str(channel_id)))

    @staticmethod
    def find_overlapping_pulses(pulse_collection):
        """
        Finds all overlapping pulses in a collection of pulses, and returns the clashing pulses. Note that only pulses
        with the same channel_id can be overlapping.

        Args:
            pulse_collection: An iterable collection of Pulse objects

        Returns:
            A list of length-2 tuples of overlapping pulses. Each pair of pulses has the earlier pulse in the first
            position

        """
        # put pulses into a dictionary, where key=channel_id and value = list of (start_time, end_time) for each pulse
        pulse_dict = {}
        for pulse in pulse_collection:
            pulse_dict.setdefault(pulse.channel_id, []).append((pulse.start_time,
                                                                pulse.start_time + pulse.duration))

        # for every channel_id, check every pair of pulses to see if they overlap
        overlapping_pulses = []
        for pulse_id, time_interval_list in pulse_dict.iteritems():
            for time_interval_pair in itertools.combinations(time_interval_list, 2):

                #this is the overlap condition for two pulses
                if time_interval_pair[0][0] < time_interval_pair[1][1] and time_interval_pair[1][0] < \
                        time_interval_pair[0][1]:
                    overlapping_pulse_1 = Pulse(pulse_id, time_interval_pair[0][0],
                                                time_interval_pair[0][1] - time_interval_pair[0][0])
                    overlapping_pulse_2 = Pulse(pulse_id, time_interval_pair[1][0],
                                                time_interval_pair[1][1] - time_interval_pair[1][0])

                    # if we find an overlap, add them to our list in ascending order of start_time
                    if overlapping_pulse_1.start_time < overlapping_pulse_2.start_time:
                        overlapping_pulses.append((overlapping_pulse_1, overlapping_pulse_2))
                    else:
                        overlapping_pulses.append((overlapping_pulse_2, overlapping_pulse_1))

        return overlapping_pulses

    def create_physical_pulse_seq(self, pulse_collection):
        """
        Creates the physical pulse sequence from a pulse_collection, adding delays to each pulse, and ensuring the first
        pulse starts at time = 0.

        Args:
            pulse_collection: An iterable collection of pulses, named tuples with (name, start_time, pulse_duration)

        Returns:
            A list of pulses.

        """

        # find the start time of the earliest pulse
        min_pulse_time = np.min([pulse.start_time for pulse in pulse_collection])

        assert min_pulse_time >= 0, 'pulse with negative start time detected, that is not a valid pulse'

        # add delays to each pulse
        delayed_pulse_collection = [Pulse(pulse.channel_id,
                                               pulse.start_time - self.get_delay(pulse.channel_id),
                                               pulse.duration)
                                    for pulse in pulse_collection]

        # make sure the pulses start at same time as min_pulse_time
        delayed_min_pulse_time = np.min([pulse.start_time for pulse in delayed_pulse_collection])
        if delayed_min_pulse_time < min_pulse_time:
            delayed_pulse_collection = [Pulse(pulse.channel_id,
                                                   pulse.start_time - delayed_min_pulse_time + min_pulse_time,
                                                   pulse.duration)
                                        for pulse in delayed_pulse_collection]

        # return the sorted list of pulses, sorted by when they start
        return delayed_pulse_collection

    def generate_pb_sequence(self, pulse_collection):
        """
        Creates a (ordered) list of PBStateChange objects for use with the pulseblaster API from a collection
        of Pulse's. Specifically, generate_pb_sequence generates a corresponding sequence of (bitstring, duration)
        objects that indicate the channels to keep on and for how long before the next instruction.

        Args:
            pulse_collection: An iterable collection of Pulse's

        Returns:
            A (ordered) list of PBStateChange objects that indicate what bitstrings to turn on at what times.

        """

        # Create a dictionary with key=time and val=list of channels to toggle at that time
        # Note: we do not specifically keep track of whether we toggle on or off at a given time (is not necessary)
        pb_command_dict = {}
        for pulse in pulse_collection:
            pb_command_dict.setdefault(pulse.start_time, []).append(1 << self.settings[pulse.channel_id]['channel'])
            pulse_end_time = pulse.start_time + pulse.duration
            pb_command_dict.setdefault(pulse_end_time, []).append(1 << self.settings[pulse.channel_id]['channel'])

        # Make sure we have a command at time=0, the command to have nothing on.
        if 0 not in pb_command_dict.keys():
            pb_command_dict[0] = 0

        # For each time, combine all of the channels we need to toggle into a single bit string, and add it to a
        # command list of PBStateChange objects
        pb_command_list = []
        for time, bit_strings in pb_command_dict.iteritems():
            channel_bits = np.bitwise_or.reduce(bit_strings)
            pb_command_list.append(PBStateChange(channel_bits, time))

        # sort the list by the time a command needs to be placed
        pb_command_list.sort(key=lambda x: x.time)

        def change_to_propogating_signal(state_change_collection):

            propogating_state_changes = []
            for i in range(0, len(state_change_collection)-1):

                # for the first command, just take the bitstring of the first element
                if i == 0:
                    new_channel_bits = state_change_collection[0].channel_bits

                # otherwise, xor with the previous bitstring we computed (in propogating_state_changes)
                else:
                    new_channel_bits = propogating_state_changes[i-1].channel_bits ^ state_change_collection[i].channel_bits

                time_between_change = state_change_collection[i+1].time - state_change_collection[i].time
                propogating_state_changes.append(PBStateChange(new_channel_bits, time_between_change))

            return propogating_state_changes

        # change this list so that instead of absolute times, they are durations, and the bitstrings properly propogate
        # i.e., if we want to keep channel 0 on at t = 1000 but now want to turn on channel 4, our bitstring would be
        # 10001 = 17 for the command at this time.
        pb_command_list = change_to_propogating_signal(pb_command_list)

        print pb_command_list
        return pb_command_list

    def _get_long_delay_breakdown(self, pb_state_change, command='CONTINUE', command_arg=0):
        """
        returns a list of PBCommand objects that correspond to a given state change and command, properly splitting up
        the state change into LONG_DELAY commands if necessary. The outputted list will always have the given command as
        the *last* command in the list.

        Args:
            pb_state_change: a PBStateChange object to find the long_delay breakdown of
            command: the command you want to initiate for this time interval
            command_arg: the argument to that command.

        Returns:
            list of PBCommand objects corresponding to a given state change.

        """

        # if the state duration is less than the LONG_DELAY threshold, return the normally formatted command
        if pb_state_change.time < self.LONG_DELAY_THRESHOLD:
            instruction_list = [PBCommand(pb_state_change.channel_bits, pb_state_change.time, command, command_arg)]
            return instruction_list

        instruction_list = []
        (num_long_delays, remainder) = divmod(pb_state_change.time, self.LONG_DELAY_THRESHOLD)

        # If the remaining time after filling with LONG_DELAYs is smaller than the minimum instruction duration,
        # split one LONG_DELAY command into one 'CONTINUE' command and one command of the type passed in
        if remainder < self.MIN_DURATION and num_long_delays > 1:
            num_long_delays -= 1
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits, self.LONG_DELAY_THRESHOLD,
                               command='LONG_DELAY', command_arg=num_long_delays))
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits , self.LONG_DELAY_THRESHOLD / 2,
                               command='CONTINUE', command_arg=0))
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits,
                               self.LONG_DELAY_THRESHOLD / 2 + remainder, command, command_arg))
            return instruction_list

        # if there aren't any more LONG_DELAYs after doing this, just send in two commands
        elif remainder < self.MIN_DURATION and num_long_delays == 1:
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits, self.LONG_DELAY_THRESHOLD / 2,
                               command='CONTINUE', command_arg=0))
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits,
                               self.LONG_DELAY_THRESHOLD / 2 + remainder, command, command_arg))
            return instruction_list

        # Otherwise, just use the LONG_DELAYs command followed by the given command for a duration given by remainder
        else:
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits, self.LONG_DELAY_THRESHOLD,
                               command='LONG_DELAY', command_arg=num_long_delays))
            instruction_list.append(
                PBCommand(pb_state_change.channel_bits, remainder, command, command_arg))
            return instruction_list

    def create_commands(self, pb_state_changes, num_loops=1):
        """
        Creates a list of commands to program the pulseblaster with, assuming that the user wants to loop over the
        state changes indicated in pb_state_changes for num_loops number of times. This function properly figures out
        when to use the LONG_DELAY pulseblaster command vs. CONTINUE, and also leaves the pulseblaster back in its
        steady-state condition when finished.

        Args:
            pb_state_changes: An ordered collection of state changes for the pulseblaster

        Returns:
            An ordered list of PBComnmand objects to program the pulseblaster with.

        """

        if len(pb_state_changes) == 0:
            return []

        # otherwise, loop over all of the given state changes for num_loops, and then leave pulseblaster in steady-state
        # settings
        pb_commands = []
        pb_commands += list(reversed(self._get_long_delay_breakdown(pb_state_changes[0], command='LOOP', command_arg=num_loops)))

        for index in range(1, len(pb_state_changes)-1):
            pb_commands += list(reversed(self._get_long_delay_breakdown(pb_state_changes[index], command='CONTINUE')))

        pb_commands += self._get_long_delay_breakdown(pb_state_changes[-1], command='END_LOOP', command_arg=0)
        pb_commands.append(PBCommand(self.settings2bits(), 100, command='BRANCH', command_arg=len(pb_commands)))
        return pb_commands

    @staticmethod
    def estimate_runtime(pulse_collection, num_loops=1):
        """
        Estimates the number of milliseconds required to complete the given pulse_collection for a given number of loops

        Args:
            pulse_collection: a collection of Pulse objects
            num_loops: the number of iterations of pulse_collection

        Returns: estimated milliseconds to complete the pulse sequence.

        """
        return float(num_loops * max([pulse.start_time + pulse.duration for pulse in pulse_collection]))/1E6

    def program_pb(self, pulse_collection, num_loops=1):
        """
        programs the pulseblaster to perform the pulses in the given pulse_collection on the next time start_pulse_seq()
        is called. The pulse collection must contain at least 2 pulses. Currently, we do not support time resolution below
        15 ns.

        Args:
            pulse_collection: A collection of Pulse objects
            num_loops: The number of times to perform the given pulse collection

        Returns:

        """

        # check for errors in the given pulse_collection
        assert len(pulse_collection) > 1, 'pulse program must have at least 2 pulses'
        assert num_loops < (1 << 20), 'cannot have more than 2^20 (approx 1 million) loop iterations'
        if self.find_overlapping_pulses(pulse_collection):
            raise AttributeError('found overlapping pulses in given pulse collection')
        for pulse in pulse_collection:
            assert pulse.start_time == 0 or pulse.start_time > 1, \
                'found a start time that was between 0 and 1. Remember pulses are in nanoseconds!'
            assert pulse.duration == 0 or pulse.duration > 1, \
                'found a pulse duration between 0 and 1. Remember pulses are in nanoseconds!'

        # process the pulse collection into a format that is designed to deal with the low-level spincore API
        delayed_pulse_collection = self.create_physical_pulse_seq(pulse_collection)
        self.estimated_runtime = self.estimate_runtime(delayed_pulse_collection, num_loops)
        pb_state_changes = self.generate_pb_sequence(delayed_pulse_collection)
        pb_commands = self.create_commands(pb_state_changes, num_loops)
        for command in pb_commands:
            if command.duration < 15:
                print('Warning, detected pulseblaster commands requiring a duration < 15 ns. The PB will likely round up'
                      'to 15 ns.')

        # begin programming the pulseblaster
        assert self.pb.pb_init() == 0, 'Could not initialize the pulseblsater on pb_init() command.'
        self.pb.pb_core_clock(ctypes.c_double(self.settings['clock_speed']))
        self.pb.pb_start_programming(self.PULSE_PROGRAM)

        for pbinstruction in pb_commands:
            # note that change types to the appropriate c type, as well as set certain bits in the channel bits to 1 in
            # order to properly output the signal
            return_value = self.pb.pb_inst_pbonly(ctypes.c_int(pbinstruction.channel_bits | 0xE00000),
                                                  self.PB_INSTRUCTIONS[pbinstruction.command],
                                                  ctypes.c_int(int(pbinstruction.command_arg)),
                                                  ctypes.c_double(pbinstruction.duration))

            assert return_value >=0, 'There was an error while programming the pulseblaster'
        self.pb.pb_stop_programming()

    def start_pulse_seq(self):
        """
        Starts the pulse sequence programmed in program_pb, and confirms that the pulseblaster is running.

        Returns:

        """

        self.pb.pb_start()
        assert self.pb.pb_read_status() & 0b100 == 0b100, 'pulseblaster did not begin running after start() called.'
        self.pb.pb_close()
        self.sequence_start_time = datetime.datetime.now()

    def wait(self):
        if self.estimated_runtime is None or self.sequence_start_time is None:
            return
        if (datetime.datetime.now() - self.sequence_start_time).microseconds/1000.0 < self.estimated_runtime:
            time.sleep(self.estimated_runtime/1000.0 - (datetime.datetime.now() - self.sequence_start_time).total_seconds())

        self.estimated_runtime = None
        self.sequence_start_time = None


class B26PulseBlaster(PulseBlaster):
    _DEFAULT_SETTINGS = Parameter([
        Parameter('laser', [
            Parameter('channel', 0, int, 'channel to which laser is connected'),
            Parameter('status', False, bool, 'True if voltage is high to the laser, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and laser switch on [ns]')
        ]),
        Parameter('apd_readout', [
            Parameter('channel', 1, int, 'channel to which the daq is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the daq, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and daq acknowledgement [ns]')
        ]),
        Parameter('microwave_p', [
            Parameter('channel', 2, int, 'channel to which the the microwave p trigger is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the microwave p trigger, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and microwave p trigger [ns]')
        ]),
        Parameter('microwave_q', [
            Parameter('channel', 3, int, 'channel to which the the microwave q trigger is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the microwave q trigger, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and microwave q trigger [ns]')
        ]),
        Parameter('microwave_switch', [
            Parameter('channel', 4, int, 'channel to which the microwave switch is connected to'),
            Parameter('status', False, bool, 'True if voltage is high to the microwave switch, false otherwise'),
            Parameter('delay_time', 0.2, float, 'delay time between pulse sending time and microwave switch [ns]')
        ]),
        Parameter('clock_speed', 100, [100, 400], 'Clock speed of the pulse blaster [MHz]')
    ])

    _PROBES = {}

    def __init__(self, name=None, settings=None):
        super(B26PulseBlaster, self).__init__(name, settings)


    def update(self, settings):
        # call the update_parameter_list to update the parameter list
        # oh god this is confusing
        super(B26PulseBlaster, self).update(settings)

    def read_probes(self):
        pass

    def get_name(self, channel):
        for key, value in self.settings:
            if 'channel' in value.keys() and value['channel'] == channel:
                return key

        raise AttributeError('Could not find instrument name attached to channel {s}'.format(channel))

if __name__=='__main__':

    pb = B26PulseBlaster()
    #pulse_collection = [Pulse('laser', 0, 100), Pulse('apd_readout', 100, 100)]
    pulse_collection = [Pulse('laser', i, 1000) for i in range(0,10000,2000)]
    pb.program_pb(pulse_collection, num_loops=1000000)
    pb.start_pulse_seq()
    pb.wait()


