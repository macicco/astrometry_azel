from pathlib import Path
import subprocess
from numpy import meshgrid, column_stack
from astropy.wcs import wcs
import logging
import xarray
from astropy.io import fits  # instead of obsolete pyfits
from dateutil.parser import parse
from datetime import datetime
from typing import Tuple
#
import pymap3d


def fits2radec(fitsfn: Path, solve: bool=False, args: str=None) -> xarray.Dataset:

    fitsfn = Path(fitsfn).expanduser()

    if fitsfn.suffix == '.fits':
        WCSfn = fitsfn.with_suffix('.wcs')  # using .wcs will also work but gives a spurious warning
    elif fitsfn.suffix == '.wcs':
        WCSfn = fitsfn
    else:
        raise ValueError(f'please convert {fitsfn} to GRAYSCALE .fits e.g. with ImageJ or ImageMagick')

    if solve:
        doSolve(fitsfn, args)

    with fits.open(fitsfn, mode='readonly') as f:
        yPix, xPix = f[0].shape[-2:]

    x, y = meshgrid(range(xPix), range(yPix))  # pixel indices to find RA/dec of
    xy = column_stack((x.ravel(order='C'), y.ravel(order='C')))
# %% use astropy.wcs to register pixels to RA/DEC
    """
    http://docs.astropy.org/en/stable/api/astropy.wcs.WCS.html#astropy.wcs.WCS
    naxis=[0,1] is to take x,y axes in case a color photo was input e.g. to astrometry.net cloud solver
    """
    try:
        with fits.open(WCSfn, mode='readonly') as f:
            # radec = wcs.WCS(hdul[0].header,naxis=[0,1]).all_pix2world(xy, 0)
            radec = wcs.WCS(f[0].header).all_pix2world(xy, 0)
    except OSError:
        raise OSError(f'It appears the WCS solution is not present, was the FITS image solved?  looking for: {WCSfn}')

    ra = radec[:, 0].reshape((yPix, xPix), order='C')
    dec = radec[:, 1].reshape((yPix, xPix), order='C')
# %% collect output
    radec = xarray.Dataset({'ra': (('y', 'x'), ra),
                            'dec': (('y', 'x'), dec), },
                           {'x': range(xPix), 'y': range(yPix)},
                           attrs={'filename': fitsfn})

    return radec


def radec2azel(scale: xarray.Dataset,
               latlon: Tuple[float, float], time: datetime=None) -> xarray.Dataset:

    if latlon is None or not isinstance(scale, xarray.Dataset):
        return None

    if time is None:
        with fits.open(scale.filename, mode='readonly') as f:
            try:
                t = f[0].header['FRAME']  # TODO this only works from Solis?
            except KeyError:
                logging.error('no time given in file or manually, cannot compute az/el')
                return None
        time = parse(t)
        logging.info('using FITS header for time')
    elif isinstance(time, datetime):
        pass
    elif isinstance(time, (float, int)):  # assume UT1_Unix
        time = datetime.utcfromtimestamp(time)
    else:  # user override of frame time
        time = parse(time)

    print('image time:', time)
# %% knowing camera location, time, and sky coordinates observed, convert to az/el for each pixel
    az, el = pymap3d.radec2azel(scale['ra'], scale['dec'], latlon[0], latlon[1], time)
# %% collect output
    scale['az'] = (('y', 'x'), az)
    scale['el'] = (('y', 'x'), el)
    scale.attrs['lat'] = latlon[0]
    scale.attrs['lon'] = latlon[1]
    scale.attrs['time'] = time

    return scale


def doSolve(fitsfn: Path, args: str=None):
    """
    Astrometry.net from at least version 0.67 is OK with Python 3.
    """
    # binpath = Path(find_executable('solve-field')).parent
    opts = args.split(' ') if args else []
# %% build command
    cmd = ['solve-field', '--overwrite', str(fitsfn)]
    cmd += opts
    print('\n', ' '.join(cmd), '\n')
# %% execute
    ret = subprocess.check_output(cmd, universal_newlines=True)

    # solve-field returns 0 even if it didn't solve!
    print(ret)
    if 'Did not solve' in ret:
        raise RuntimeError(f'could not solve {fitsfn}')

    print('\n\n *** done with astrometry.net ***\n ')


def fits2azel(fitsfn: Path,
              latlon: Tuple[float, float],
              time: datetime=None, solve: bool=False, args: str=None) -> xarray.Dataset:

    fitsfn = Path(fitsfn).expanduser()

    radec = fits2radec(fitsfn, solve, args)
    scale = radec2azel(radec, latlon, time)

# %% if az/el can be computed, scale is implicitly merged with radec. Otherwise just return radec
    if scale is None:
        scale = radec

    return scale
