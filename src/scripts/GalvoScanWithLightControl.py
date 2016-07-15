from src.core import Script, Parameter
from src.instruments import MaestroLightControl
from src.scripts import GalvoScan

class GalvoScanWithLightControl(Script):
    """
Takes an image based in galvo scan script and controls light with MaestroLightControl instrument
    """

    _DEFAULT_SETTINGS = [
        Parameter('light_mode','fluorescence', ['fluorescence', 'reflection'])
    ]

    _INSTRUMENTS = {'MaestroLightControl': MaestroLightControl}

    _SCRIPTS = {'acquire_image': GalvoScan}


    def __init__(self, instruments, scripts, name=None, settings=None, log_function=None, data_path=None):

        Script.__init__(self, name, settings=settings, instruments=instruments, scripts = scripts, log_function=log_function, data_path=data_path)

    def _function(self):

        instrument_settings = self.instruments['MaestroLightControl']['settings']

        if self.settings['light_mode'] == 'fluorescence':
            instrument_settings.update({
                'white light':{'open':False},
                'filter wheel': {'current_position': 'red_filter'},
                'block IR': {'open': False},
                'block green': {'open': True}
            })

        elif  self.settings['light_mode'] == 'reflection':
            instrument_settings.update({
                'white light':{'open':False},
                'filter wheel': {'current_position': 'ND1.0'},
                'block IR': {'open': False},
                'block green': {'open': True}
            })
        else:
            raise TypeError('unknown light mode')

        self.instruments['MaestroLightControl']['instance'].update(instrument_settings)

        self.data = self.scripts['acquire_image'].data

        self.scripts['acquire_image'].run()

        if self.settings['save']:
            self.save_b26()
            self.save_data()
            self.save_log()

    def _plot(self, axes_list):
        # this implementation is needed if superscript want to make use of it
        self.scripts['acquire_image']._plot(axes_list)

    def _update_plot(self, axes_list):
        # this implementation is needed if superscript want to make use of it
        self.scripts['acquire_image']._update_plot(axes_list)
    def plot(self, figure_list):
        self.scripts['acquire_image'].plot(figure_list)


if __name__ == '__main__':
    from src.core import Instrument

    script, failed, instr = Script.load_and_append({'GalvoScan': 'GalvoScan'})

    instr, failed = Instrument.load_and_append({'MaestroLightControl': 'MaestroLightControl'}, instruments=instr)

    print(script)
    print(failed)
    print(instr)
