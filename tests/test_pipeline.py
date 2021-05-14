"""

By using this code you agree to the terms of the software license agreement.

© Copyright 2020 Wyss Center for Bio and Neuro Engineering – All rights reserved
"""

from time import time
from pipapr.parser import tileParser
from pipapr.stitcher import tileStitcher
from pipapr.viewer import tileViewer
from pipapr.segmenter import tileSegmenter
import os
import numpy as np
import pyapr


def compute_gradients(apr, parts, sobel=True):
    """
    Compute gradient for each spatial direction directly on APR.

    Parameters
    ----------
    apr: (APR) APR object
    parts: (ParticleData) particle data sampled on APR
    sobel: (bool) use sobel filter to compute the gradient

    Returns
    -------
    (dx, dy, dz): (arrays) gradient for each direction
    """

    par = apr.get_parameters()
    dx = pyapr.FloatParticles()
    dy = pyapr.FloatParticles()
    dz = pyapr.FloatParticles()

    pyapr.numerics.gradient(apr, parts, dz, dimension=2, delta=par.dz, sobel=sobel)
    pyapr.numerics.gradient(apr, parts, dx, dimension=1, delta=par.dx, sobel=sobel)
    pyapr.numerics.gradient(apr, parts, dy, dimension=0, delta=par.dy, sobel=sobel)
    return dz, dx, dy


def compute_laplacian(apr, parts, grad=None, sobel=True):
    """
    Compute Laplacian for each spatial direction directly on APR.

    Parameters
    ----------
    apr: (APR) APR object
    parts: (ParticleData) particle data sampled on APR
    grad: (dz, dy, dx) gradient for each direction if precomputed (faster for Laplacian computation)
    sobel: (bool) use sobel filter to compute the gradient

    Returns
    -------
    Laplacian of APR.
    """

    par = apr.get_parameters()
    if grad is None:
        dz, dx, dy = compute_gradients(apr, parts, sobel)
    else:
        dz, dx, dy = grad
    dx2 = pyapr.FloatParticles()
    dy2 = pyapr.FloatParticles()
    dz2 = pyapr.FloatParticles()
    pyapr.numerics.gradient(apr, dz, dz2, dimension=2, delta=par.dz, sobel=sobel)
    pyapr.numerics.gradient(apr, dx, dx2, dimension=1, delta=par.dx, sobel=sobel)
    pyapr.numerics.gradient(apr, dy, dy2, dimension=0, delta=par.dy, sobel=sobel)
    return dz2 + dx2 + dy2


def compute_gradmag(apr, parts, sobel=True):
    """
    Compute gradient magnitude directly on APR.

    Parameters
    ----------
    apr: (APR) APR object
    parts: (ParticleData) particle data sampled on APR
    sobel: (bool) use sobel filter to compute the gradient

    Returns
    -------
    Gradient magnitude of APR.
    """

    par = apr.get_parameters()
    gradmag = pyapr.FloatParticles()
    pyapr.numerics.gradient_magnitude(apr, parts, gradmag, deltas=(par.dz, par.dx, par.dy), sobel=sobel)
    return gradmag


def gaussian_blur(apr, parts, sigma=1.5, size=11):
    """
    Compute Gaussian blur directly on APR.

    Parameters
    ----------
    apr: (APR) APR object
    parts: (ParticleData) particle data sampled on APR
    sigma: (float) Gaussian blur standard deviation (kernel radius)
    size: (int) kernel size (increase with caution, complexity is not linear)

    Returns
    -------
    Blurred APR.
    """

    stencil = pyapr.numerics.get_gaussian_stencil(size, sigma, ndims=3, normalize=True)
    output = pyapr.FloatParticles()
    pyapr.numerics.filter.convolve_pencil(apr, parts, output, stencil, use_stencil_downsample=True,
                                          normalize_stencil=True, use_reflective_boundary=True)
    return output


def particle_levels(apr):
    """
    Returns apr level: for each particle the lvl is defined as the size of the particle in pixel.

    Parameters
    ----------
    apr: (APR) APR object

    Returns
    -------
    Particle level.
    """

    lvls = pyapr.ShortParticles(apr.total_number_particles())
    lvls.fill_with_levels(apr)
    lvls = np.array(lvls)

    return 2 ** (lvls.max() - lvls)


def compute_features(apr, parts):
    gauss = gaussian_blur(apr, parts, sigma=1.5, size=11)
    print('Gaussian computed.')

    # Compute gradient magnitude (central finite differences)
    grad = compute_gradmag(apr, gauss)
    print('Gradient magnitude computed.')
    # Compute lvl for each particle
    lvl = particle_levels(apr)
    print('Particle level computed.')
    # Compute difference of Gaussian
    dog = gaussian_blur(apr, parts, sigma=3, size=22) - gauss
    print('DOG computed.')
    lapl_of_gaussian = compute_laplacian(apr, gauss)
    print('Laplacian of Gaussian computed.')

    # Aggregate filters in a feature array
    f = np.vstack((np.array(parts, copy=True),
                   lvl,
                   gauss,
                   grad,
                   lapl_of_gaussian,
                   dog
                   )).T

    return f


def get_cc_from_features(apr, parts_pred):

    # Create a mask from particle classified as cells (cell=0, background=1, membrane=2)
    parts_cells = (parts_pred == 0)

    # Use opening to separate touching cells
    pyapr.numerics.transform.opening(apr, parts_cells, radius=1, binary=True, inplace=True)

    # Apply connected component
    cc = pyapr.LongParticles()
    pyapr.numerics.segmentation.connected_component(apr, parts_cells, cc)

    # Remove small objects
    # cc = pyapr.numerics.transform.remove_small_objects(apr, cc, 128)

    return cc


path = r'../data'
path_classifier=r'../data/random_forest_n100.joblib'
t = time()
t_ini = time()
tiles = tileParser(path, frame_size=512, overlap=128, type='apr')
print('Elapsed time parse data: {:.2f} ms.'.format((time() - t)*1000))
t = time()
stitcher = tileStitcher(tiles)
stitcher.activate_mask(99)
# stitcher.activate_segmentation(path_classifier, compute_features, get_cc_from_features, verbose=True)
stitcher.compute_registration()
print('Elapsed time load, segment, and compute pairwise reg: {:.2f} s.'.format(time() - t))
t = time()
stitcher.build_sparse_graphs()
print('Elapsed time build sparse graph: {:.2f} ms.'.format((time() - t)*1000))
t = time()
stitcher.optimize_sparse_graphs()
print('Elapsed time optimize graph: {:.2f} ms.'.format((time() - t)*1000))
stitcher.plot_min_trees(annotate=True)
t = time()
reg_rel_map, reg_abs_map = stitcher.produce_registration_map()
print('Elapsed time reg map: {:.2f} ms.'.format((time() - t)*1000))
t = time()
stitcher.build_database(tiles)
print('Elapsed time build database: {:.2f} ms.'.format((time() - t)*1000))
t = time()
stitcher.save_database(os.path.join(path, 'registration_results.csv'))
print('Elapsed time save database: {:.2f} ms.'.format((time() - t)*1000))

print('\n\nTOTAL elapsed time: {:.2f} s.'.format(time() - t_ini))
#
# from pipapr.segmenter import tileCells
# cells = tileCells(tiles, stitcher.database)
# cells.extract_and_merge_cells(lowe_ratio=0.7, distance_max=50)
#
viewer = tileViewer(tiles, stitcher.database)
coords= []
for i in range(4):
    for j in range(4):
        coords.append([i, j])
coords = np.array(coords)
viewer.display_all_tiles(level_delta=0, contrast_limits=[0, 3000])