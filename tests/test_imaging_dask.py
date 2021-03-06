"""Unit tests for pipelines expressed via dask.delayed


"""

import os
import unittest

import numpy
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.wcs.utils import pixel_to_skycoord
from dask import delayed

from arl.calibration.operations import apply_gaintable, create_gaintable_from_blockvisibility
from arl.data.polarisation import PolarisationFrame
from arl.fourier_transforms.ftprocessor import create_image_from_visibility, predict_skycomponent_blockvisibility, \
    invert_wstack_single, predict_wstack_single
from arl.graphs.dask_graphs import create_invert_facet_graph, create_predict_facet_graph, \
    create_zero_vis_graph_list, create_subtract_vis_graph_list, create_deconvolve_facet_graph, \
    create_invert_wstack_graph, create_residual_wstack_graph, create_predict_wstack_graph
from arl.image.operations import qa_image, export_image_to_fits
from arl.skycomponent.operations import create_skycomponent, insert_skycomponent
from arl.util.testing_support import create_named_configuration, simulate_gaintable
from arl.visibility.operations import create_blockvisibility
from arl.visibility.operations import qa_visibility


class TestImagingDask(unittest.TestCase):
    def setUp(self):
        
        self.results_dir = './test_results'
        os.makedirs(self.results_dir, exist_ok=True)
        
        self.invert = invert_wstack_single
        self.predict = predict_wstack_single
        
        self.npixel = 256
        self.facets = 2
        
        self.setupVis(add_errors=False)
        self.model_graph = delayed(self.get_LSM)(self.vis_graph_list[self.nvis // 2], npixel=self.npixel)
    
    def setupVis(self, add_errors=False):
        self.freqwin = 3
        self.vis_graph_list = list()
        for freq in numpy.linspace(0.8e8, 1.2e8, self.freqwin):
            self.vis_graph_list.append(delayed(self.ingest_visibility)(freq, add_errors=add_errors))
        
        self.nvis = len(self.vis_graph_list)
        self.wstep = 10.0
        self.vis_slices = 2 * int(numpy.ceil(numpy.max(numpy.abs(self.vis_graph_list[0].compute().w)) / self.wstep)) + 1
    
    def ingest_visibility(self, freq=1e8, chan_width=1e6, time=0.0, reffrequency=[1e8], add_errors=False):
        lowcore = create_named_configuration('LOWBD2-CORE')
        times = [time]
        frequency = numpy.array([freq])
        channel_bandwidth = numpy.array([chan_width])
        
        #        phasecentre = SkyCoord(ra=+180.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox=2000.0)
        # Observe at zenith to ensure that timeslicing works well. We test that elsewhere.
        phasecentre = SkyCoord(ra=+180.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox=2000.0)
        vt = create_blockvisibility(lowcore, times, frequency, channel_bandwidth=channel_bandwidth,
                                    weight=1.0, phasecentre=phasecentre,
                                    polarisation_frame=PolarisationFrame("stokesI"))
        cellsize = 0.001
        model = create_image_from_visibility(vt, npixel=self.npixel, cellsize=cellsize, npol=1,
                                             frequency=reffrequency,
                                             polarisation_frame=PolarisationFrame("stokesI"))
        flux = numpy.array([[100.0]])
        facets = 4
        
        rpix = model.wcs.wcs.crpix - 1
        spacing_pixels = self.npixel // facets
        centers = [-1.5, -0.5, 0.5, 1.5]
        comps = list()
        for iy in centers:
            for ix in centers:
                p = int(round(rpix[0] + ix * spacing_pixels * numpy.sign(model.wcs.wcs.cdelt[0]))), \
                    int(round(rpix[1] + iy * spacing_pixels * numpy.sign(model.wcs.wcs.cdelt[1])))
                sc = pixel_to_skycoord(p[0], p[1], model.wcs, origin=0)
                comps.append(create_skycomponent(flux=flux, frequency=vt.frequency, direction=sc,
                                                 polarisation_frame=PolarisationFrame("stokesI")))
        predict_skycomponent_blockvisibility(vt, comps)
        insert_skycomponent(model, comps)
        export_image_to_fits(model, '%s/test_imaging_dask_model.fits' % (self.results_dir))
        
        if add_errors:
            gt = create_gaintable_from_blockvisibility(vt)
            gt = simulate_gaintable(gt, phase_error=1.0, amplitude_error=0.0)
            vt = apply_gaintable(vt, gt)
        return vt
    
    def get_LSM(self, vt, npixel=512, cellsize=0.001, reffrequency=[1e8], flux=0.0):
        model = create_image_from_visibility(vt, npixel=self.npixel, cellsize=cellsize, npol=1,
                                             frequency=reffrequency,
                                             polarisation_frame=PolarisationFrame("stokesI"))
        model.data[..., 32, 32] = flux
        return model
    
    def test_predict_wstack_graph(self):
        flux_model_graph = delayed(self.get_LSM)(self.vis_graph_list[self.nvis // 2], npixel=self.npixel,
                                                 flux=100.0)
        zero_vis_graph_list = create_zero_vis_graph_list(self.vis_graph_list)
        predicted_vis_graph_list = create_predict_wstack_graph(zero_vis_graph_list, flux_model_graph,
                                                               vis_slices=self.vis_slices)
        residual_vis_graph_list = create_subtract_vis_graph_list(self.vis_graph_list,
                                                                 predicted_vis_graph_list)
        
        qa = qa_visibility(self.vis_graph_list[0].compute())
        numpy.testing.assert_almost_equal(qa.data['maxabs'], 1600.0, 0)
        
        qa = qa_visibility(predicted_vis_graph_list[0].compute())
        numpy.testing.assert_almost_equal(qa.data['maxabs'], 100.064844507, 0)
        
        qa = qa_visibility(residual_vis_graph_list[0].compute())
        numpy.testing.assert_almost_equal(qa.data['maxabs'], 1654.6573274952634, 0)
    
    def test_predict_facet_graph(self):
        flux_model_graph = delayed(self.get_LSM)(self.vis_graph_list[self.nvis // 2], npixel=self.npixel,
                                                 flux=100.0)
        zero_vis_graph_list = create_zero_vis_graph_list(self.vis_graph_list)
        predicted_vis_graph_list = create_predict_facet_graph(zero_vis_graph_list, flux_model_graph,
                                                              vis_slices=self.vis_slices)
        residual_vis_graph_list = create_subtract_vis_graph_list(self.vis_graph_list,
                                                                 predicted_vis_graph_list)
        
        qa = qa_visibility(self.vis_graph_list[0].compute())
        numpy.testing.assert_almost_equal(qa.data['maxabs'], 1600.0, 0)
        
        qa = qa_visibility(predicted_vis_graph_list[0].compute())
        numpy.testing.assert_almost_equal(qa.data['maxabs'], 100.064844507, 0)
        
        qa = qa_visibility(residual_vis_graph_list[0].compute())
        numpy.testing.assert_almost_equal(qa.data['maxabs'], 1654.6573274952634, 0)
    
    def test_invert_wstack_graph(self):
        
        dirty_graph = create_invert_wstack_graph(self.vis_graph_list, self.model_graph,
                                                 dopsf=False, normalize=True,
                                                 vis_slices=self.vis_slices)
        
        dirty = dirty_graph.compute()
        export_image_to_fits(dirty[0], '%s/test_imaging_dask_invert_dirty.fits' % (self.results_dir))
        qa = qa_image(dirty[0])
        
        assert numpy.abs(qa.data['max'] - 104.0) < 1.0
        assert numpy.abs(qa.data['min'] + 5.0) < 1.0
    
    def test_invert_facet_graph(self):
        
        dirty_graph = create_invert_facet_graph(self.vis_graph_list, self.model_graph,
                                                dopsf=False, normalize=True, facets=self.facets)
        
        dirty = dirty_graph.compute()
        export_image_to_fits(dirty[0], '%s/test_imaging_dask_invert_facet_dirty.fits' % (self.results_dir))
        qa = qa_image(dirty[0])
        
        assert numpy.abs(qa.data['max'] - 104.0) < 1.0
        assert numpy.abs(qa.data['min'] + 5.0) < 1.0
    
    def test_residual_wstack_graph(self):
        
        self.model_graph = delayed(self.get_LSM)(self.vis_graph_list[self.nvis // 2],
                                                 npixel=self.npixel, flux=100.0)
        
        dirty_graph = create_residual_wstack_graph(self.vis_graph_list, self.model_graph,
                                                   vis_slices=self.vis_slices)
        
        dirty = dirty_graph.compute()
        export_image_to_fits(dirty[0], '%s/test_imaging_dask_residual_residual_slices%d.fits' %
                             (self.results_dir, self.vis_slices))
        
        qa = qa_image(dirty[0])
        
        assert numpy.abs(qa.data['max'] - 104.0) < 5.0
        assert numpy.abs(qa.data['min'] + 5.0) < 5.0
    
    def test_deconvolution_facet_graph(self):
        
        facets = 4
        model_graph = delayed(self.get_LSM)(self.vis_graph_list[self.nvis // 2],
                                            npixel=self.npixel, flux=0.0)
        dirty_graph = create_invert_facet_graph(self.vis_graph_list, model_graph,
                                                vis_slices=self.vis_slices,
                                                dopsf=False)
        
        psf_model_graph = delayed(self.get_LSM)(self.vis_graph_list[self.nvis // 2],
                                                npixel=self.npixel, flux=0.0)
        psf_graph = create_invert_wstack_graph(self.vis_graph_list, psf_model_graph,
                                               vis_slices=self.vis_slices,
                                               dopsf=True)
        
        clean_graph = create_deconvolve_facet_graph(dirty_graph, psf_graph, model_graph,
                                                    algorithm='hogbom', niter=1000,
                                                    fractional_threshold=0.02, threshold=2.0,
                                                    gain=0.1, facets=facets)
        result = clean_graph.compute()
        
        export_image_to_fits(result, '%s/test_imaging_dask_deconvolution_facets%d.clean.fits' %
                             (self.results_dir, facets))
        
        qa = qa_image(result)
        
        assert numpy.abs(qa.data['max'] - 94.0) < 5.0
        assert numpy.abs(qa.data['min'] + 8.0) < 5.0
    
