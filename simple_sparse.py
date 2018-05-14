import numpy as np
import scipy.sparse as scisp
import sparse


def is_hermitian(m, tol=1e-6):
    """
    Test that a sparse matrix is hermitian (also suffices for symmetric)
    :param m: square matrix
    :param tol: tolernace above zero for m - m.T < tol
    :return: True matrix is Hermitian
    """
    return np.all(~(np.abs(m - m.H) >= tol).todense())


def tensor_print(T):
    """
    Pretty print a dense (numpy) 4D matrix. Users should consider the size of the matrix before
    printing, as they can be large! More useful for smaller objects
    :param T: the tensor to print wit dim: (N,M,n,m)
    """

    try:
        pw = int(np.ceil(np.log10(T.max())))
    except OverflowError:
        pw = 1
    for i in xrange(T.shape[0]):
        for k in xrange(T.shape[2]):
            print '|',
            for j in xrange(T.shape[1]):
                print '[',
                for l in xrange(T.shape[3]):
                    print '{0:{1}d}'.format(T[i, j, k, l], pw),

                print ']',
            print '|'
        if i < T.shape[1] - 2:
            print '+'
    print


def kr_biostochastic(m, tol=1e-6, x0=None, delta=0.1, Delta=3, verbose=False, max_iter=1000):
    """
    Normalise a matrix to be bistochastic using Knight-Ruiz algorithm. This method is expected
    to converge more quickly.
    :param m: the input matrix (fully symmetric)
    :param tol: precision tolerance
    :param x0: an initial guess
    :param delta: how close balancing vector can get
    :param Delta: how far balancing vector can get
    :param verbose: print debug info
    :param max_iter: maximum number of iterations before abandoning.
    :return: tuple containing the bistochastic matrix and the scale factors
    """
    assert scisp.isspmatrix(m), 'input matrix must be sparse matrix from scipy.spmatrix'
    assert m.shape[0] == m.shape[1], 'input matrix must be square'
    if not scisp.isspmatrix_csr(m):
        m = m.tocsr()
    try:
        assert is_hermitian(m, tol), 'input matrix is expected to be fully symmetric'
    except AssertionError as e:
        import warnings
        warnings.warn(e.message)

    n = m.shape[0]
    e = np.ones(n)

    if not x0:
        x0 = e.copy()

    g = 0.9
    etamax = 0.1
    eta = etamax
    stop_tol = tol * 0.5

    x = x0.copy()
    rt = tol ** 2
    v = x * m.dot(x)

    rk = 1 - v
    rho_km1 = rk.T.dot(rk)  # transpose possibly implicit
    rout = rho_km1
    rold = rout

    n_iter = 0
    i = 0
    y = np.empty_like(e)
    while rout > rt and n_iter < max_iter:

        i += 1
        k = 0
        y[:] = e

        inner_tol = max(rout * eta ** 2, rt)

        while rho_km1 > inner_tol:

            k += 1
            if k == 1:
                Z = rk / v
                p = Z
                rho_km1 = rk.T.dot(Z)
            else:
                beta = rho_km1 / rho_km2
                p = Z + beta * p

            w = x * m.dot(x * p) + v * p
            alpha = rho_km1 / p.T.dot(w)
            ap = alpha * p

            ynew = y + ap

            if np.amin(ynew) <= delta:
                if delta == 0:
                    break
                ind = np.where(ap < 0)[0]
                gamma = np.amin((delta - y[ind]) / ap[ind])
                y += gamma * ap
                break

            if np.amax(ynew) >= Delta:
                ind = np.where(ynew > Delta)[0]
                gamma = np.amin((Delta - y[ind]) / ap[ind])
                y += gamma * ap
                break

            y = ynew
            rk = rk - alpha * w
            rho_km2 = rho_km1

            Z = rk * v
            rho_km1 = np.dot(rk.T, Z)

            if np.any(np.isnan(x)):
                raise RuntimeError('scale vector has developed invalid values (NANs)!')

        x *= y
        v = x * m.dot(x)

        rk = 1 - v
        rho_km1 = np.dot(rk.T, rk)
        rout = rho_km1
        n_iter += k + 1

        rat = rout / rold
        rold = rout
        res_norm = np.sqrt(rout)
        eta_o = eta
        eta = g * rat

        if g * eta_o ** 2 > 0.1:
            eta = max(eta, g * eta_o ** 2)
        eta = max(min(eta, etamax), stop_tol / res_norm)

    if verbose:
        print 'It took {} iterations to achieve bistochasticity'.format(n_iter)

    if n_iter >= max_iter:
        print 'Warning: maximum number of iterations ({}) reached without convergence'.format(max_iter)

    X = scisp.spdiags(x, 0, n, n, 'csr')
    return X.T.dot(m.dot(X)), x


class Sparse2DAccumulator(object):

    def __init__(self, N):
        self.shape = (N, N)
        self.mat = {}
        # fixed counting type
        self.dtype = np.uint32

    def __setitem__(self, index, value):
        assert len(index) == 2 and index[0] >= 0 and index[1] >= 0, 'invalid index: {}'.format(index)
        assert isinstance(value, int), 'values must be integers'
        self.mat[index] = value

    def __getitem__(self, index):
        if index in self.mat:
            return self.mat[index]
        else:
            return 0

    def get_coo(self, symm=True):
        """
        Create a COO format sparse representation of the accumulated values.
        :param symm: ensure matrix is symmetric on return
        :return: a scipy.coo_matrix sparse matrix
        """
        _coords = [[], []]
        _data = []
        _m = self.mat
        for i, j in _m.keys():
            assert i <= j, 'fuck off'

            _coords[0].append(i)
            _coords[1].append(j)
            _data.append(_m[i, j])

        _m = scisp.coo_matrix((_data, _coords), shape=self.shape, dtype=self.dtype)

        if symm:
            _m += scisp.tril(_m.T, k=-1)

        return _m.tocoo()


def max_offdiag(_m):
    """
    Determine the maximum off-diagonal values of a given symmetric matrix. As this
    is assumed to be symmetric, we consider only the rows.
    :param _m: a scipy.sparse matrix
    :return: the off-diagonal maximum values
    """
    assert scisp.isspmatrix(_m), 'Input matrix is not a scipy.sparse object'
    _m = _m.tolil(True)
    _m.setdiag(0)
    return np.asarray(_m.tocsr().max(axis=0).todense()).ravel()


def compress(_m, _mask):
    """
    Remove rows and columns using a 1d boolean mask.
    :param _mask: True (keep), False (drop)
    :return: a coo_matrix of only the accepted rows/columns
    """
    assert scisp.isspmatrix(_m), 'Input matrix is not a scipy sparse matrix type'

    if not scisp.isspmatrix_coo(_m):
        _m = _m.tocoo()

    # collect those values not in the excluded rows/columns
    keep_row = []
    keep_col = []
    keep_data = []
    accept_index = set(np.where(_mask)[0])
    for i in xrange(_m.nnz):
        if _m.row[i] in accept_index and _m.col[i] in accept_index:
            keep_row.append(_m.row[i])
            keep_col.append(_m.col[i])
            keep_data.append(_m.data[i])

    # adjustments for removed rows/column indices
    shift = np.cumsum(~_mask)
    # TODO move this in the above loop
    for i in xrange(len(keep_row)):
        keep_row[i] -= shift[keep_row[i]]
        keep_col[i] -= shift[keep_col[i]]

    return scisp.coo_matrix((keep_data, (keep_row, keep_col)), shape=_m.shape - shift[-1])


class Sparse4DAccumulator(object):
    """
    Simple square sparse tensor of dimension (N, N, 2, 2)
    There is limited functionality and mainly intended to save memory while not performing operations.
    """
    def __init__(self, N):
        self.shape = (N, N, 2, 2)
        self.mat = {}
        # fixed counting type
        self.dtype = np.uint32

    def __setitem__(self, index, value):
        assert isinstance(index, tuple), 'index must be a list of indices'
        if len(index) == 4:
            assert 0 <= index[0] < self.shape[0] and \
                   0 <= index[1] < self.shape[1] and \
                   0 <= index[2] < 2 and \
                   0 <= index[3] < 2, 'invalid range {} for dimension {}'.format(index, self.shape)

            if index[:2] not in self.mat and np.any(value != 0):
                self.mat.setdefault(index[:2], self._make_elem())[index[2:]] = value

        if len(index) == 2:
            assert 0 <= index[0] < self.shape[0] and \
                   0 <= index[1] < self.shape[1], 'invalid range {} for dimension {}'.format(index, self.shape)

            if index not in self.mat:
                self.mat.setdefault(index, self._make_elem())[:] = value

    def __getitem__(self, index):
        return self.mat.setdefault(index, self._make_elem())

    def _make_elem(self):
        return np.zeros((2, 2), dtype=self.dtype)

    def get_coo(self, symm=True):
        """
        Create a COO format sparse representation of the accumulated values. NOTE: As scipy
        does not support multidimensional arrays, this object is from the "sparse" module.
        :param symm: ensure matrix is symmetric on return
        :return: a sparse.COO matrix
        """
        _coords = [[], [], [], []]
        _data = []
        _m = self.mat
        _inner_indices = [[0, 0], [0, 1], [1, 0], [1, 1]]
        for i, j in _m.keys():
            for k, l in _inner_indices:
                v = _m[i, j][k, l]
                if v != 0:
                    _coords[0].append(i)
                    _coords[1].append(j)
                    _coords[2].append(k)
                    _coords[3].append(l)
                    _data.append(v)

        _m = sparse.COO(_coords, _data, self.shape, has_duplicates=False)

        if symm:
            _m = Sparse4DAccumulator.symm(_m)

        return _m

    @staticmethod
    def _flip(c_row):
        """
        Flip indices (coordinates) as pairs: (i,j), (k,l) -> (j,i), (l,k)
        :param c_row: coordinate row to flip
        :return the flipped indices
        """
        c_row = c_row.copy()
        c_row[0], c_row[1] = c_row[1], c_row[0]
        c_row[2], c_row[3] = c_row[3], c_row[2]
        return c_row

    @staticmethod
    def symm(_m):
        """
        Make a 4D COO matrix symmetric, all elements above and below the diagonal are included.
        Duplicate entries will be summed.
        :param _m: the NxNx2x2 matrix to make symmetric
        :return: a new symmetric version
        """
        # collect indices of diagonal elements along primary axes (0 and 1)
        ix = np.where(~np.apply_along_axis(lambda x: x[0]==x[1], 0, _m.coords))[0]
        # append every non-zero, non-diag coord and accompanying data to a new sparse object
        # and also perform the transpose (i,j), (k,l) -> (j,i), (l,k)
        _coords = np.hstack((_m.coords, np.apply_along_axis(Sparse4DAccumulator._flip, 0, _m.coords[:,ix])))
        _data = np.hstack((_m.data, _m.data[ix]))
        return sparse.COO(_coords, _data, shape=_m.shape, has_duplicates=True)


def max_offdiag_4d(_m):
    """
    Determine the maximum off-diagonal summed signal, where "summed signal" refers to reducing the
    the tensor to a 2d matrix by summing over the last two axes (2x2 submatrices).
    :param _m: a 4d sparse.COO or DOK matrix with dimension NxNx2x2.
    :return: a vector of length N containing off-diagonal maximums.
    """
    return max_offdiag(_m.sum(axis=(2, 3)).tocsr())


def flatten_tensor_4d(_m):
    """
    Flatten a 4D tensor into 2D by doubling the first two dimensions. It is assumed that the matrix
    has already been made symmetric (if required).
    :param _m: a 4d sparse.COO matrix with dimension NxNx2x2
    :return: 2d sparse matrix of type scipy.sparse.coo_matrix
    """
    _coords = [[], []]
    _data = []
    for n in xrange(_m.nnz):
        i, j, k, l = _m.coords[:, n]
        ii = 2*i
        jj = 2*j
        _coords[0].append(ii+k)
        _coords[1].append(jj+l)
        _data.append(_m.data[n])

    _m = scisp.coo_matrix((_data, _coords), shape=(2*_m.shape[0], 2*_m.shape[1]))
    return _m


def compress_4d(_m, _mask):
    """
    Remove rows and columns of a sparse 4D matrix using a 1d boolean mask. Masking operates on
    only the first two primary axes (essentially a 2D matrix with 2x2 cells). If the input is not
    of sparse.COO type, it will be cast. An exception is raised if the matrix is not of
     sparse.DOK or sparse.COO type. The returned matrix is of type sparse.COO.
    :param _mask: True (keep), False (drop)
    :return: a sparse.COO of only the accepted rows/columns
    """
    assert isinstance(_m, (sparse.COO, sparse.DOK)), 'Input matrix must be of sparse.COO or sparse.DOK type'
    if not isinstance(_m, sparse.COO):
        _m = _m.to_coo()

    # collect those values not in the excluded rows/columns
    keep_coords = []
    keep_data = []
    accept_index = set(np.where(_mask)[0])
    for i in xrange(_m.nnz):
        if _m.coords[0, i] in accept_index and _m.coords[1, i] in accept_index:
            keep_coords.append(_m.coords[:, i])
            keep_data.append(_m.data[i])
    keep_coords = np.array(keep_coords, dtype=np.int).T

    # remaining data needs adjustments to compensate for removed rows/column indices
    shift = np.cumsum(~_mask, dtype=np.int)
    keep_coords[:2, :] -= shift[keep_coords[:2, :]]

    # create new smaller matrix
    new_shape = list(_m.shape)
    new_shape[:2] -= shift[-1]
    return sparse.COO(keep_coords, keep_data, shape=new_shape, has_duplicates=False)