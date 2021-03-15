"""
Derived module from dmdbase.py for dmd with control.

Reference:
- Proctor, J.L., Brunton, S.L. and Kutz, J.N., 2016. Dynamic mode decomposition
with control. SIAM Journal on Applied Dynamical Systems, 15(1), pp.142-161.
"""
from .dmdbase import DMDBase
from past.utils import old_div
import numpy as np
from .dmdoperator import DMDOperator

class DMDControlOperator(DMDOperator):
    def __init__(self, svd_rank_omega=-1, **kwargs):
        super(DMDControlOperator, self).__init__(**kwargs)
        self._svd_rank_omega = svd_rank_omega

class DMDBKnownOperator(DMDControlOperator):
    def compute_operator(self, X, Y, B, controlin):
        Y = Y - B.dot(controlin)
        return super(DMDBKnownOperator, self).compute_operator(X,Y)

class DMDBUnknownOperator(DMDControlOperator):
    def compute_operator(self, X, Y, controlin, snapshots_rows):
        omega = np.vstack([X, controlin])

        Up, sp, Vp = self._compute_svd(omega, self._svd_rank_omega)

        Up1 = Up[:snapshots_rows, :]
        Up2 = Up[snapshots_rows:, :]

        Ur, sr, Vr = self._compute_svd(Y, self._svd_rank)

        self._Atilde = Ur.T.conj().dot(Y).dot(Vp).dot(np.diag(
            np.reciprocal(sp))).dot(Up1.T.conj()).dot(Ur)
        self._compute_eigenquantities()
        self._compute_modes_and_Lambda(Y, sp, Vp, Up1, Ur)

        Btilde = Ur.T.conj().dot(Y).dot(Vp).dot(np.diag(
            np.reciprocal(sp))).dot(Up2.T.conj())

        return Ur, Ur.dot(Btilde)

    def _compute_modes_and_Lambda(self, Y, sp, Vp, Up1, Ur):
        self._modes = Y.dot(Vp).dot(np.diag(np.reciprocal(sp))).dot(
            Up1.T.conj()).dot(Ur).dot(self.eigenvectors)
        self._Lambda = self.eigenvalues

class DMDc(DMDBase):
    """
    Dynamic Mode Decomposition with control.
    This version does not allow to manipulate the temporal window within the
    system is reconstructed.

    :param svd_rank: the rank for the truncation; If 0, the method computes the
        optimal rank and uses it for truncation; if positive interger, the
        method uses the argument for the truncation; if float between 0 and 1,
        the rank is the number of the biggest singular values that are needed
        to reach the 'energy' specified by `svd_rank`; if -1, the method does
        not compute truncation.
    :type svd_rank: int or float
    :param int tlsq_rank: rank truncation computing Total Least Square. Default
        is 0, that means no truncation.
    :param bool opt: flag to compute optimal amplitudes. See :class:`DMDBase`.
        Default is False.
    :param svd_rank_omega: the rank for the truncation of the aumented matrix
        omega composed by the left snapshots matrix and the control. Used only
        for the `_fit_B_unknown` method of this class. It should be greater or
        equal than `svd_rank`. For the possible values please refer to the
        `svd_rank` parameter description above.
    :param rescale_mode: Scale Atilde as shown in
            10.1016/j.jneumeth.2015.10.010 (section 2.4) before computing its
            eigendecomposition. None means no rescaling, 'auto' means automatic
            rescaling using singular values, otherwise the scaling factors.
    :type rescale_mode: {'auto'} or None or numpy.ndarray
    :type svd_rank_omega: int or float
    """
    def __init__(self, tlsq_rank=0, opt=False, **kwargs):
        super(DMDc, self).__init__(tlsq_rank=tlsq_rank, opt=opt, rescale_mode=None, **kwargs)

        self._B = None
        self._snapshots_shape = None
        self._controlin = None
        self._controlin_shape = None
        self._basis = None

    def _initialize_dmdoperator(self, **kwargs):
        # we're going to initialize Atilde when we know if B is known
        self._Atilde = None
        # remember the arguments for when we'll need them
        self._dmd_operator_kwargs = kwargs

    @property
    def B(self):
        """
        Get the operator B.

        :return: the operator B.
        :rtype: numpy.ndarray
        """
        return self._B

    @property
    def basis(self):
        """
        Get the basis used to reduce the linear operator to the low dimensional
        space.

        :return: the matrix which columns are the basis vectors.
        :rtype: numpy.ndarray
        """
        return self._basis

    def reconstructed_data(self, control_input=None):
        """
        Return the reconstructed data, computed using the `control_input`
        argument. If the `control_input` is not passed, the original input (in
        the `fit` method) is used. The input dimension has to be consistent
        with the dynamics.

        :param numpy.ndarray control_input: the input control matrix.
        :return: the matrix that contains the reconstructed snapshots.
        :rtype: numpy.ndarray
        """
        if control_input is None:
            controlin, controlin_shape = self._controlin, self._controlin_shape
        else:
            controlin, controlin_shape = self._col_major_2darray(control_input)

        if controlin.shape[1] != self.dynamics.shape[1] - 1:
            raise RuntimeError(
                'The number of control inputs and the number of snapshots to reconstruct has to be the same'
            )

        eigs = np.power(self.eigs,
                        old_div(self.dmd_time['dt'], self.original_time['dt']))
        A = self.modes.dot(np.diag(eigs)).dot(np.linalg.pinv(self.modes))

        data = [self._snapshots[:, 0]]

        for i, u in enumerate(controlin.T):
            data.append(A.dot(data[i]) + self._B.dot(u))

        data = np.array(data).T
        return data

    def fit(self, X, I, B=None):
        """
        Compute the Dynamic Modes Decomposition with control given the original
        snapshots and the control input data. The matrix `B` that controls how
        the control input influences the system evolution can be provided by
        the user; otherwise, it is computed by the algorithm.

        :param X: the input snapshots.
        :type X: numpy.ndarray or iterable
        :param I: the control input.
        :type I: numpy.ndarray or iterable
        :param numpy.ndarray B: matrix that controls the control input
            influences the system evolution.
        :type B: numpy.ndarray or iterable
        """
        self._snapshots, self._snapshots_shape = self._col_major_2darray(X)
        self._controlin, self._controlin_shape = self._col_major_2darray(I)

        n_samples = self._snapshots.shape[1]
        X = self._snapshots[:, :-1]
        Y = self._snapshots[:, 1:]

        self.original_time = {'t0': 0, 'tend': n_samples - 1, 'dt': 1}
        self.dmd_time = {'t0': 0, 'tend': n_samples - 1, 'dt': 1}

        if B is None:
            self._Atilde = DMDBUnknownOperator(**self._dmd_operator_kwargs)
            self._basis, self._B = self._Atilde.compute_operator(X, Y, self._controlin, self._snapshots.shape[0])
        else:
            self._Atilde = DMDBKnownOperator(**self._dmd_operator_kwargs)
            U, _, _ = self._Atilde.compute_operator(X, Y, B, self._controlin)

            self._basis = U
            self._B = B

        self._b = self._compute_amplitudes()

        return self
