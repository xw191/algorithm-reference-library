"""Unit tests for skycomponents

"""

import logging
import os
import unittest

import astropy.units as u
import numpy
from astropy.coordinates import SkyCoord

from arl.data.polarisation import PolarisationFrame
from arl.fourier_transforms.ftprocessor import invert_2d, predict_2d, create_image_from_visibility
from arl.image.deconvolution import restore_cube
from arl.image.operations import export_image_to_fits
from arl.skycomponent.operations import insert_skycomponent, create_skycomponent
from arl.util.testing_support import create_test_image, create_named_configuration
from arl.visibility.operations import create_visibility
from arl.image.solvers import solve_image

log = logging.getLogger(__name__)


class Testskycomponent(unittest.TestCase):
    def setUp(self):
        self.dir = './test_results'
        self.lowcore = create_named_configuration('LOWBD2-CORE')
        os.makedirs(self.dir, exist_ok=True)
        self.times = (numpy.pi / (12.0)) * numpy.linspace(-3.0, 3.0, 7)
        self.frequency = numpy.array([1e8])
        self.channel_bandwidth = numpy.array([1e6])
        self.phasecentre = SkyCoord(ra=+180.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox=2000.0)
        self.vis = create_visibility(self.lowcore, self.times, self.frequency,
                                     channel_bandwidth=self.channel_bandwidth,
                                     phasecentre=self.phasecentre, weight=1.0,
                                     polarisation_frame=PolarisationFrame('stokesI'))
        self.vis.data['vis'] *= 0.0
        
        # Create model
        self.model = create_test_image(cellsize=0.0015, phasecentre=self.vis.phasecentre,
                                       frequency=self.frequency)
        self.model.data[self.model.data > 1.0] = 1.0
        self.vis = predict_2d(self.vis, self.model)
        assert numpy.max(numpy.abs(self.vis.vis)) > 0.0
        export_image_to_fits(self.model, '%s/test_solve_skycomponent_model.fits' % (self.dir))
        self.bigmodel = create_image_from_visibility(self.vis, cellsize=0.0015, npixel=512)
        
        
    def test_insert_skycomponent(self):
        sc = create_skycomponent(direction=self.phasecentre, flux=numpy.array([[1.0]]), frequency=self.frequency,
                                 polarisation_frame = PolarisationFrame('stokesI'))
        
        log.debug(self.model.wcs)
        log.debug(str(sc))
        # The actual phase centre of a numpy FFT is at nx //2, nx //2 (0 rel).
        self.model.data *= 0.0
        insert_skycomponent(self.model, sc)
        npixel = self.model.shape[3]
        rpix = numpy.round(self.model.wcs.wcs.crpix).astype('int')
        assert rpix[0] == npixel // 2
        assert rpix[1] == npixel // 2
        assert self.model.data[0,0,rpix[1],rpix[0]] == 1.0
        self.vis = predict_2d(self.vis, self.model)
        assert self.vis.vis.imag.all() == 0.0

    def test_insert_skycomponent_lanczos(self):
        sc = create_skycomponent(direction=self.phasecentre, flux=numpy.array([[1.0]]), frequency=self.frequency,
                                 polarisation_frame=PolarisationFrame('stokesI'))

        dphasecentre = SkyCoord(ra=+181.0 * u.deg, dec=-58.0 * u.deg, frame='icrs', equinox=2000.0)
        sc = create_skycomponent(direction=dphasecentre, flux=numpy.array([[1.0]]), frequency=self.frequency,
                                 polarisation_frame=PolarisationFrame('stokesI'))
        self.model.data *= 0.0
        insert_skycomponent(self.model, sc, insert_method='Lanczos')
        npixel = self.model.shape[3]
        rpix = numpy.round(self.model.wcs.wcs.crpix).astype('int')
        assert rpix[0] == npixel // 2
        assert rpix[1] == npixel // 2
        # These test a regression but are not known a priori to be correct
        self.assertAlmostEqual(self.model.data[0,0,119,150],  0.887186883218, 7)
        self.assertAlmostEqual(self.model.data[0,0,119,151], -0.145093950704, 7)

if __name__ == '__main__':
    unittest.main()
