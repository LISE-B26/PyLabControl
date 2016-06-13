from src.core import Script, Parameter
from PySide.QtCore import Signal, QThread
import numpy as np
from collections import deque
from src.instruments.labview_fpga import NI7845RGalvoScan
from src.plotting.plots_2d import plot_fluorescence
from copy import deepcopy
import time
import threading
import Queue
import datetime

class GalvoScanNIFpga(Script, QThread):
# class GalvoScanNIFpga(Script):
    """
    GalvoScan uses the apd, daq, and galvo to sweep across voltages while counting photons at each voltage,
    resulting in an image in the current field of view of the objective.
    """
    updateProgress = Signal(int)

    _DEFAULT_SETTINGS = Parameter([
        Parameter('path',  'tmp_data', str, 'path to folder where data is saved'),
        Parameter('tag', 'some_name'),
        Parameter('save', False, bool,'check to automatically save data'),
        Parameter('max_counts_plot', -1, int, 'Rescales colorbar with this as the maximum counts on replotting')
    ])

    _INSTRUMENTS = {'NI7845RGalvoScan':  NI7845RGalvoScan}

    _SCRIPTS = {}

    def __init__(self, instruments, name = None, settings = None, log_function = None, timeout = 1000000000, data_path = None):
        self.timeout = timeout
        self.plot_widget = None

        Script.__init__(self, name, settings=settings, instruments=instruments, log_function=log_function, data_path = data_path)

        QThread.__init__(self)

        self._plot_type = 'main'

        self.queue = Queue.Queue()


    def _function(self):
        """
        This is the actual function that will be executed. It uses only information that is provided in the settings property
        will be overwritten in the __init__
        """

        instr = self.instruments['NI7845RGalvoScan']['instance']
        instr_settings = self.instruments['NI7845RGalvoScan']['settings']

        def init_scan():
            self._recording = False
            #self._plotting = False
            self._abort = False
            instr.update(instr_settings)

            Nx = instr_settings['num_points']['x']
            Ny = instr_settings['num_points']['y']
            time_per_pt = instr_settings['time_per_pt']
            N_per_pt = int(time_per_pt/2.5e-3)
            extent = instr.pts_to_extent(instr_settings['point_a'], instr_settings['point_b'], instr_settings['RoI_mode'])

            self.data = {'image_data': np.zeros((Nx, Ny)), 'extent': extent}

            return Nx, Ny, N_per_pt

        Nx, Ny, N_per_pt = init_scan()

        instr.start_acquire()

        i = 0

        t1 = datetime.datetime.now()
        time_per_line = Nx*instr_settings['time_per_pt']*N_per_pt
        print('N_per_pt', N_per_pt)
        print('time_per_line', time_per_line)
        print('instr_settings', instr_settings)
        while i < Ny:
            if self._abort:
                break
            # print('acquiring line {:02d}/{:02d}'.format(i, Ny))
            elem_written = instr.elements_written_to_dma
            # print('elem_written ', elem_written)
            if elem_written >= N_per_pt*Nx:
                line_data = instr.read_fifo(N_per_pt*Nx)
                sig = line_data['signal'].reshape(Nx,N_per_pt)
                self.data['image_data'][i] = deepcopy(np.mean(sig,1))
                i +=1
            # wait time it takes acquire a point
            time.sleep(time_per_line)

            t2 = datetime.datetime.now()

            # if acquisition is too fast wait to not drive gui crazy, we choose 2 updates per second
            if t2 - t1 > datetime.timedelta(seconds=0.5):
                progress = int(float(i + 1) / Ny * 100)
                self.updateProgress.emit(progress)
                t1 = t2
                print(unicode(datetime.datetime.now()))

                diagnostics = {
                    'acquire': instr.acquire,
                    'elements_written_to_dma': instr.elements_written_to_dma,
                    'DMATimeOut': instr.acquire,
                    'ix': instr.ix,
                    'iy': instr.iy,
                    'detector_signal': instr.detector_signal,
                    'Nx': instr.Nx,
                    'Ny': instr.Ny,
                    'running': instr.running,
                    'DMA_elem_to_write': instr.DMA_elem_to_write,
                    'loop_time': instr.loop_time,
                    'meas_per_pt':instr.meas_per_pt,
                    'settle_time': instr.settle_time
                }

                print(diagnostics)


        if self.settings['save']:
            self.save_b26()
            self.save_data()
            self.save_log()
            self.save_image_to_disk()

        self.updateProgress.emit(100)

    @staticmethod
    def pts_to_extent(pta, ptb, roi_mode):
        """

        Args:
            pta: point a
            ptb: point b
            roi_mode:   mode how to calculate region of interest
                        corner: pta and ptb are diagonal corners of rectangle.
                        center: pta is center and ptb is extend or rectangle

        Returns: extend of region of interest [xVmin, xVmax, yVmax, yVmin]

        """
        if roi_mode == 'corner':
            xVmin = min(pta['x'], ptb['x'])
            xVmax = max(pta['x'], ptb['x'])
            yVmin = min(pta['y'], ptb['y'])
            yVmax = max(pta['y'], ptb['y'])
        elif roi_mode == 'center':
            xVmin = pta['x'] - float(ptb['x']) / 2.
            xVmax = pta['x'] + float(ptb['x']) / 2.
            yVmin = pta['y'] - float(ptb['y']) / 2.
            yVmax = pta['y'] + float(ptb['y']) / 2.
        return [xVmin, xVmax, yVmax, yVmin]

    def plot(self, image_figure, axes_colorbar = None):
        axes_image = self.get_axes(image_figure)
        plot_fluorescence(self.data['image_data'], self.data['extent'], axes_image, max_counts = self.settings['max_counts_plot'], axes_colorbar=axes_colorbar)

    def stop(self):
        self._abort = True


if __name__ == '__main__':
    script, failed, instruments = Script.load_and_append(script_dict={'GalvoScanNIFpga': 'GalvoScanNIFpga'})

    print(script)
    print(failed)
    gs = script['GalvoScanNIFpga']
    print(gs)

    print(gs.instruments['NI7845RGalvoScan']['instance'].settings)

    gs.run()
    print(gs.data)
