""" Visibility operations

"""

import copy

from arl.data.polarisation import correlate_polarisation
from arl.fourier_transforms.ftprocessor_params import *
from arl.util.coordinate_support import *
from arl.visibility.iterators import vis_timeslice_iter

log = logging.getLogger(__name__)


def vis_summary(vis):
    """Return string summarizing the Visibility
    
    """
    return "%d rows, %.3f GB" % (vis.nvis, vis.size())


def append_visibility(vis: Visibility, othervis: Visibility):
    """Append othervis to vis
    
    :param vis:
    :param othervis:
    :returns: Visibility vis + othervis
    """
    assert vis.polarisation_frame == othervis.polarisation_frame
    assert vis.phasecentre == othervis.phasecentre
    vis.data = numpy.hstack((vis.data, othervis.data))
    return vis


def copy_visibility(vis, zero=False):
    """Copy a visibility
    
    Performs a deepcopy of the data array
    """
    newvis = copy.copy(vis)
    newvis.data = copy.deepcopy(vis.data)
    if zero:
        newvis.data['vis'][...] = 0.0
    return newvis


def create_visibility(config: Configuration, times: numpy.array, frequency: numpy.array,
                      channel_bandwidth, phasecentre: SkyCoord,
                      weight: float, polarisation_frame=PolarisationFrame('stokesI'),
                      integration_time=1.0) -> Visibility:
    """ Create a Visibility from Configuration, hour angles, and direction of source

    Note that we keep track of the integration time for BDA purposes

    :param config: Configuration of antennas
    :param times: hour angles in radians
    :param frequency: frequencies (Hz] Shape [nchan]
    :param weight: weight of a single sample
    :param phasecentre: phasecentre of observation
    :param npol: Number of polarizations
    :param integration_time: Integration time ('auto' or value in s)
    :returns: Visibility
    """
    assert phasecentre is not None, "Must specify phase centre"
    
    if polarisation_frame is None:
        polarisation_frame = correlate_polarisation(config.receptor_frame)
    
    nch = len(frequency)
    ants_xyz = config.data['xyz']
    nants = len(config.data['names'])
    nbaselines = int(nants * (nants - 1) / 2)
    ntimes = len(times)
    npol = polarisation_frame.npol
    nrows = nbaselines * ntimes * nch
    nrowsperintegration = nbaselines * nch
    row = 0
    rvis = numpy.zeros([nrows, npol], dtype='complex')
    rweight = weight * numpy.ones([nrows, npol])
    rtimes = numpy.zeros([nrows])
    rfrequency = numpy.zeros([nrows])
    rchannel_bandwidth = numpy.zeros([nrows])
    rantenna1 = numpy.zeros([nrows], dtype='int')
    rantenna2 = numpy.zeros([nrows], dtype='int')
    ruvw = numpy.zeros([nrows, 3])
    
    # Do each hour angle in turn
    for iha, ha in enumerate(times):
        
        # Calculate the positions of the antennas as seen for this hour angle
        # and declination
        ant_pos = xyz_to_uvw(ants_xyz, ha, phasecentre.dec.rad)
        rtimes[row:row + nrowsperintegration] = ha * 43200.0 / numpy.pi
        
        # Loop over all pairs of antennas. Note that a2>a1
        for a1 in range(nants):
            for a2 in range(a1 + 1, nants):
                rantenna1[row:row + nch] = a1
                rantenna2[row:row + nch] = a2
                
                # Loop over all frequencies and polarisations
                for ch in range(nch):
                    # noinspection PyUnresolvedReferences
                    k = frequency[ch] / constants.c.value
                    ruvw[row, :] = (ant_pos[a2, :] - ant_pos[a1, :]) * k
                    rfrequency[row] = frequency[ch]
                    rchannel_bandwidth[row] = channel_bandwidth[ch]
                    row += 1
    
    assert row == nrows
    rintegration_time = numpy.full_like(rtimes, integration_time)
    vis = Visibility(uvw=ruvw, time=rtimes, antenna1=rantenna1, antenna2=rantenna2,
                     frequency=rfrequency, vis=rvis,
                     weight=rweight, imaging_weight=rweight,
                     integration_time=rintegration_time, channel_bandwidth=rchannel_bandwidth,
                     polarisation_frame=polarisation_frame)
    vis.phasecentre = phasecentre
    vis.configuration = config
    log.info("create_visibility: %s" % (vis_summary(vis)))
    assert type(vis) is Visibility, "vis is not a Visibility: %r" % vis
    
    return vis


def create_blockvisibility(config: Configuration, times: numpy.array, frequency: numpy.array, phasecentre: SkyCoord,
                           weight: float, polarisation_frame=None, integration_time=1.0,
                           channel_bandwidth=1e6) -> BlockVisibility:
    """ Create a BlockVisibility from Configuration, hour angles, and direction of source

    Note that we keep track of the integration time for BDA purposes

    :param config: Configuration of antennas
    :param times: hour angles in radians
    :param frequency: frequencies (Hz] Shape [nchan]
    :param weight: weight of a single sample
    :param phasecentre: phasecentre of observation
    :param npol: Number of polarizations
    :param integration_time: Integration time ('auto' or value in s)
    :returns: BlockVisibility
    """
    assert phasecentre is not None, "Must specify phase centre"
    
    if polarisation_frame is None:
        polarisation_frame = correlate_polarisation(config.receptor_frame)
    
    nch = len(frequency)
    ants_xyz = config.data['xyz']
    nants = len(config.data['names'])
    nbaselines = int(nants * (nants - 1) / 2)
    ntimes = len(times)
    npol = polarisation_frame.npol
    visshape = [ntimes, nants, nants, nch, npol]
    rvis = numpy.zeros(visshape, dtype='complex')
    rweight = weight * numpy.ones(visshape)
    rtimes = numpy.zeros([ntimes])
    ruvw = numpy.zeros([ntimes, nants, nants, 3])
    
    # Do each hour angle in turn
    for iha, ha in enumerate(times):
        
        # Calculate the positions of the antennas as seen for this hour angle
        # and declination
        ant_pos = xyz_to_uvw(ants_xyz, ha, phasecentre.dec.rad)
        rtimes[iha] = ha * 43200.0 / numpy.pi
        
        # Loop over all pairs of antennas. Note that a2>a1
        for a1 in range(nants):
            for a2 in range(a1 + 1, nants):
                ruvw[iha, a2, a1, :] = (ant_pos[a2, :] - ant_pos[a1, :])
                ruvw[iha, a1, a2, :] = (ant_pos[a1, :] - ant_pos[a2, :])
    
    rintegration_time = numpy.full_like(rtimes, integration_time)
    rchannel_bandwidth = numpy.full_like(frequency, channel_bandwidth)
    vis = BlockVisibility(uvw=ruvw, time=rtimes, frequency=frequency, vis=rvis, weight=rweight,
                          integration_time=rintegration_time, channel_bandwidth=rchannel_bandwidth,
                          polarisation_frame=polarisation_frame)
    vis.phasecentre = phasecentre
    vis.configuration = config
    log.info("create_visibility: %s" % (vis_summary(vis)))
    assert type(vis) is BlockVisibility, "vis is not a BlockVisibility: %r" % vis
    
    return vis


def create_visibility_from_rows(vis: Visibility, rows, makecopy=True) -> Visibility:
    """ Create a Visibility or BlockVisibility from selected rows

    :param vis: Visibility
    :param rows: Boolean array of row selction
    :param makecopy: Make a deep copy (True)
    :returns: Visibility
    """
    
    if type(vis) is Visibility:
    
        if makecopy:
            newvis = copy_visibility(vis)
            newvis.data = copy.deepcopy(vis.data[rows])
            return newvis
        else:
            vis.data = copy.deepcopy(vis.data[rows])
            return vis
    else:

        if makecopy:
            newvis = copy_visibility(vis)
            newvis.data = copy.deepcopy(vis.data[rows])
            return newvis
        else:
            vis.data = copy.deepcopy(vis.data[rows])
            
            return vis


def phaserotate_visibility(vis: Visibility, newphasecentre: SkyCoord, tangent=True,
                           inverse=False) -> Visibility:
    """
    Phase rotate from the current phase centre to a new phase centre

    :param vis: Visibility to be rotated
    :param newphasecentre:
    :param tangent: Stay on the same tangent plane? (True)
    :param inverse: Actually do the opposite
    :returns: Visibility
    """
    assert type(vis) is Visibility, "vis is not a Visibility: %r" % vis
    
    l, m, n = skycoord_to_lmn(newphasecentre, vis.phasecentre)
    
    # No significant change?
    if numpy.abs(l) > 1e-15 or numpy.abs(m) > 1e-15:
        
        # Make a new copy
        newvis = copy_visibility(vis)
        
        phasor = simulate_point(newvis.uvw, l, m)
        
        if inverse:
            for pol in range(vis.polarisation_frame.npol):
                newvis.data['vis'][..., pol] *= phasor
        else:
            for pol in range(vis.polarisation_frame.npol):
                newvis.data['vis'][..., pol] *= numpy.conj(phasor)
        
        # To rotate UVW, rotate into the global XYZ coordinate system and back. We have the option of
        # staying on the tangent plane or not. If we stay on the tangent then the raster will
        # join smoothly at the edges. If we change the tangent then we will have to reproject to get
        # the results on the same image, in which case overlaps or gaps are difficult to deal with.
        if not tangent:
            if inverse:
                xyz = uvw_to_xyz(vis.data['uvw'], ha=-newvis.phasecentre.ra.rad, dec=newvis.phasecentre.dec.rad)
                newvis.data['uvw'][...] = \
                    xyz_to_uvw(xyz, ha=-newphasecentre.ra.rad, dec=newphasecentre.dec.rad)[...]
            else:
                # This is the original (non-inverse) code
                xyz = uvw_to_xyz(newvis.data['uvw'], ha=-newvis.phasecentre.ra.rad, dec=newvis.phasecentre.dec.rad)
                newvis.data['uvw'][...] = xyz_to_uvw(xyz, ha=-newphasecentre.ra.rad, dec=newphasecentre.dec.rad)[
                    ...]
        newvis.phasecentre = newphasecentre
    
    return newvis


def sum_visibility(vis: Visibility, direction: SkyCoord) -> numpy.array:
    """ Direct Fourier summation in a given direction

    :param vis: Visibility to be summed
    :param direction: Direction of summation
    :returns: flux[nch,npol], weight[nch,pol]
    """
    # TODO: Convert to Visibility or remove?
    
    assert type(vis) is Visibility, "vis is not a Visibility: %r" % vis
    
    l, m, n = skycoord_to_lmn(direction, vis.phasecentre)
    phasor = numpy.conjugate(simulate_point(vis.uvw, l, m))
    
    # Need to put correct mapping here
    _, frequency = get_frequency_map(vis, None)
    
    frequency = list(frequency)
    
    nchan = max(frequency) + 1
    npol = vis.polarisation_frame.npol
    
    flux = numpy.zeros([nchan, npol])
    weight = numpy.zeros([nchan, npol])
    
    coords = vis.vis, vis.weight, phasor, list(frequency)
    for v, wt, p, ic in zip(*coords):
        for pol in range(npol):
            flux[ic, pol] += numpy.real(wt[pol] * v[pol] * p)
            weight[ic, pol] += wt[pol]
    
    flux[weight > 0.0] = flux[weight > 0.0] / weight[weight > 0.0]
    flux[weight <= 0.0] = 0.0
    return flux, weight


def qa_visibility(vis, context=None):
    """Assess the quality of Visibility

    :param vis: Visibility to be assessed
    :returns: AQ
    """
    avis = numpy.abs(vis.vis)
    data = {'maxabs': numpy.max(avis),
            'minabs': numpy.min(avis),
            'rms': numpy.std(avis),
            'medianabs': numpy.median(avis)}
    qa = QA(origin=None,
            data=data,
            context=context)
    return qa


def remove_continuum_blockvisibility(vis: BlockVisibility, degree=1, mask=None, **kwargs):
    """ Fit and remove continuum visibility

    Fit a polynomial in frequency of the specified degree where mask is True

    
    :param vis:
    :param deg:
    :param mask:
    :param kwargs:
    :return:
    """
    if mask is not None:
        assert numpy.sum(mask) > 2 * degree, "Insufficient channels for fit"
    
    nchan = len(vis.frequency)
    x = (vis.frequency - vis.frequency[nchan//2])/(vis.frequency[0] - vis.frequency[nchan//2])
    for row in range(vis.nvis):
        for ant2 in range(vis.nants):
            for ant1 in range(vis.nants):
                for pol in range(vis.polarisation_frame.npol):
                    wt = numpy.sqrt(vis.data['weight'][row, ant2, ant1, :, pol])
                    if mask is not None:
                        wt[mask] = 0.0
                    fit = numpy.polyfit(x, vis.data['vis'][row, ant2, ant1, :, pol], w=wt, deg=degree)
                    prediction = numpy.polyval(fit, x)
                    vis.data['vis'][row, ant2, ant1, :, pol] -= prediction
    return vis
