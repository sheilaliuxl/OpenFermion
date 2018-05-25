#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""This module is to find lowest eigenvalues with Davidson algorithm."""
from __future__ import absolute_import

import numpy
import numpy.linalg
import scipy
import scipy.linalg
import scipy.sparse.linalg

from openfermion.utils._sparse_tools import (get_linear_qubit_operator,
                                             get_linear_qubit_operator_diagonal)

class DavidsonError(Exception):
    """Exceptions."""
    pass


class Davidson(object):
    """Davidson algorithm to get the n states with smallest eigenvalues."""

    def __init__(self, linear_operator, linear_operator_diagonal, eps=1e-6):
        """
        Args:
            linear_operator(scipy.sparse.linalg.LinearOperator): The linear
                operator which defines a dot function when applying on a vector.
            linear_operator_diagonal(numpy.ndarray): The linear operator's
                diagonal elements.
            eps(float): The max error for eigen vector error's elements during
                iterations: linear_operator * v - v * lambda.
        """
        if not isinstance(linear_operator, scipy.sparse.linalg.LinearOperator):
            raise ValueError(
                'linear_operator is not a LinearOperator: {}.'.format(type(
                    linear_operator)))

        self.linear_operator = linear_operator
        self.linear_operator_diagonal = linear_operator_diagonal
        self.eps = eps

    def get_lowest_n(self, n_lowest=1, initial_guess=None, max_iterations=300):
        """
        Returns `n` smallest eigenvalues and corresponding eigenvectors for
            linear_operator.

        Args:
            n(int): The number of states corresponding to the smallest eigenvalues
                and associated eigenvectors for the linear_operator.
            initial_guess(numpy.ndarray[complex]): Initial guess of eigenvectors
                associated with the `n` smallest eigenvalues.
            max_iterations(int): Max number of iterations when not converging.

        Returns:
            success(bool): Indicates whether it converged, i.e. max elementwise
                error is smaller than eps.
            eigen_values(numpy.ndarray[complex]): The smallest n eigenvalues.
            eigen_vectors(numpy.ndarray[complex]): The smallest n eigenvectors
                  corresponding with those eigen values.
        """
        # Goes through a few checks and preprocessing before iterative
        # diagonalization.

        # 1. Checks for number of states desired, should be in the range of
        # [0, dimension].
        if n_lowest <= 0 or n_lowest > len(self.linear_operator_diagonal):
            raise ValueError('n_lowest is supposed to be in [{}, {}].'.format(
                n_lowest, len(self.linear_operator_diagonal)))

        # 2. Checks for initial guess vectors' dimension is the same to that of
        # the operator.
        if initial_guess.shape[0] != len(self.linear_operator_diagonal):
            raise ValueError('Guess vectors have a different dimension with '
                             'linear opearator diagonal elements: {} != {}.'
                             .format(initial_guess.shape[1],
                                     len(self.linear_operator_diagonal)))

        # 3. Checks for non-trivial (non-zero) initial guesses.
        if numpy.max(numpy.abs(initial_guess)) < self.eps:
            raise ValueError('Guess vectors are all zero!'.format(
                initial_guess.shape))
        initial_guess = scipy.linalg.orth(initial_guess)

        # 4. Makes sure number of initial guess vector is at least n_lowest.
        if initial_guess.shape[1] < n_lowest:
            initial_guess = self.append_random_vectors(
                initial_guess, n_lowest - initial_guess.shape[1])

        success = False
        num_iterations = 0
        guess_v = initial_guess
        guess_mv = None
        while (num_iterations < max_iterations and not success):
            eigen_values, eigen_vectors, max_trial_error, guess_v, guess_mv = (
                self._iterate(n_lowest, guess_v, guess_mv))

            if max_trial_error < self.eps:
                success = True
                break

            # Deals with new directions to make sure they're orthonormal.
            count_mvs = guess_mv.shape[1]
            guess_v = self.orthonormalize(guess_v, count_mvs)
            num_trial = 0
            while guess_v.shape[1] <= count_mvs and num_trial < 3:
                # No new directions are available, generates random directions.
                guess_v = numpy.hstack([
                    guess_v,
                    (numpy.random.rand(guess_mv.shape[0], n_lowest) +
                     numpy.random.rand(guess_mv.shape[0], n_lowest) * 1.0j)])
                guess_v = self.orthonormalize(guess_v, count_mvs)
                num_trial += 1
            num_iterations += 1
        return success, eigen_values, eigen_vectors

    def _generate_random_vectors(self, col, row=None):
        """Generates orthonormal random vectors with col columns.

        Args:
            col(int): Number of columns desired.
            row(int): Number of rows for the vectors.

        Returns:
            random_vectors(numpy.ndarray(complex)): Orthonormal random vectors.
        """
        if row is None:
            row = len(self.linear_operator_diagonal)

        random_vectors = (numpy.random.rand(row, col) +
                          numpy.random.rand(row, col) * 1.0j)
        random_vectors = scipy.linalg.orth(random_vectors)
        return random_vectors

    def append_random_vectors(self, vectors, col):
        """Appends exactly col orthonormal random vectors for vectors.

        Assumes vectors is already orthonormal.

        Args:
            vectors(numpy.ndarray(complex)): Orthonormal original vectors to be
                appended.
            col(int): Number of columns to be appended.

        Returns:
            vectors(numpy.ndarray(complex)): Orthonormal vectors with n columns.
        """
        vector_columns = vectors.shape[1]
        total_columns = vector_columns + col
        if total_columns > vectors.shape[0]:
            raise ValueError(
                'Asking for too many random vectors: {} > {}.'.format(
                    total_columns, vectors.shape[0]))

        num_trial = 0
        while vector_columns < total_columns:
            num_trial += 1

            vectors = numpy.hstack([vectors, self._generate_random_vectors(
                total_columns - vector_columns, row=vectors.shape[0])])
            self.orthonormalize(vectors, vector_columns)

            # Checks whether there are any new vectors added successfully.
            if vectors.shape[1] == vector_columns:
                if (num_trial) > 3:
                    # Not able to generate new directions for vectors.
                    break
            else:
                num_trial = 1
                vector_columns = vectors.shape[1]
        return vectors

    def orthonormalize(self, vectors, num_orthonormals=1):
        """Orthonormalize vectors, so that they're all normalized and orthogoal.

        The first vector is the same to that of vectors, while vector_i is
        orthogonal to vector_j, where j < i.

        Args:
            vectors(numpy.ndarray(complex)): Input vectors to be
                orthonormalized.
            num_orthonormals(int): First `num_orthonormals` columns are already
                orthonormal, so that one doesn't need to make any changes.

        Returns:
            ortho_normals(numpy.ndarray(complex)): Output orthonormal vectors.
        """
        num_vectors = vectors.shape[1]
        if num_vectors == 0:
            raise ValueError(
                'vectors is not supposed to be empty: {}.'.format(vectors.shape))

        ortho_normals = vectors
        count_orthonormals = num_orthonormals
        # Skip unchanged ones.
        for i in range(num_orthonormals, num_vectors):
            vector_i = vectors[:, i]
            # Makes sure vector_i is orthogonal to all processed vectors.
            for j in range(i):
                vector_i -= ortho_normals[:, j] * numpy.dot(
                    ortho_normals[:, j].conj(), vector_i)

            # Makes sure vector_i is normalized.
            if numpy.max(numpy.abs(vector_i)) < self.eps:
                continue
            ortho_normals[:, count_orthonormals] = (vector_i /
                                                    numpy.linalg.norm(vector_i))
            count_orthonormals += 1
        return ortho_normals[:, :count_orthonormals]

    def _iterate(self, n_lowest, guess_v, guess_mv=None):
        """One iteration with guess vectors.

        Args:
            n_lowest(int): The first n_lowest number of eigenvalues and
                eigenvectors one is interested in.
            guess_v(numpy.ndarray(complex)): Guess eigenvectors associated with
                the smallest eigenvalues.
            guess_mv(numpy.ndarray(complex)): Matrix applied on guess_v,
                therefore they should have the same dimension.

        Returns:
            trial_lambda(numpy.ndarray(float)): The minimal eigenvalues based on
                guess eigenvectors.
            trial_v(numpy.ndarray(complex)): New guess eigenvectors.
            max_trial_error(float): The max elementwise error for all guess
                vectors.

            guess_v(numpy.ndarray(complex)): Cached guess eigenvectors to avoid
               recalculation for the next iterations.
            guess_mv(numpy.ndarray(complex)): Cached guess vectors which is the
                matrix product of linear_operator with guess_v.
        """
        # TODO: optimize for memory usage, so that one can limit max number of
        # guess vectors to keep.

        if guess_mv is None:
            guess_mv = self.linear_operator * guess_v
        dimension = guess_v.shape[1]

        # Note that getting guess_mv is the most expensive step.
        if guess_mv.shape[1] < dimension:
            guess_mv = numpy.hstack([guess_mv, self.linear_operator *
                                     guess_v[:, guess_mv.shape[1] : dimension]])
        guess_vmv = numpy.dot(guess_v.conj().T, guess_mv)

        # Gets new set of eigenvalues and eigenvectors in the vmv space, with a
        # smaller dimension which is the number of vectors in guess_v.
        #
        # Note that we don't get the eigenvectors directly, instead we only get
        # a transformation based on the raw vectors, so that mv don't need to be
        # recalculated.
        trial_lambda, trial_transformation = numpy.linalg.eigh(guess_vmv)

        # Sorts eigenvalues in ascending order.
        sorted_index = list(reversed(trial_lambda.argsort()[::-1]))
        trial_lambda = trial_lambda[sorted_index]
        trial_transformation = trial_transformation[:, sorted_index]

        if len(trial_lambda) > n_lowest:
            trial_lambda = trial_lambda[:n_lowest]
            trial_transformation = trial_transformation[:, :n_lowest]

        # Estimates errors based on diagonalization in the smaller space.
        trial_v = numpy.dot(guess_v, trial_transformation)
        trial_mv = numpy.dot(guess_mv, trial_transformation)
        trial_error = trial_mv - trial_v * trial_lambda

        new_directions, max_trial_error = self._get_new_directions(
            trial_error, trial_lambda, trial_v)
        if new_directions:
            guess_v = numpy.hstack([guess_v, numpy.stack(new_directions).T])
        return trial_lambda, trial_v, max_trial_error, guess_v, guess_mv

    def _get_new_directions(self, error_v, trial_lambda, trial_v):
        """Gets new directions from error vectors.

        Args:
            error_v(numpy.ndarray(complex)): Error vectors from the guess
                eigenvalues and associated eigenvectors.
            trial_lambda(numpy.ndarray(float)): The n_lowest minimal guess
                eigenvalues.
            trial_v(numpy.ndarray(complex)): Guess eigenvectors associated with
                trial_lambda.

        Returns:
            new_directions(numpy.ndarray(complex)): New directions for searching
                for real eigenvalues and eigenvectors.
            max_trial_error(float): The max elementwise error for all guess
                vectors.
        """
        n_lowest = error_v.shape[1]

        max_trial_error = 0
        # Adds new guess vectors for the next iteration for the first n_lowest
        # directions.
        origonal_dimension = error_v.shape[0]

        new_directions = []
        for i in range(n_lowest):
            current_error_v = error_v[:, i]

            if numpy.max(numpy.abs(current_error_v)) < self.eps:
                # Already converged for this eigenvector, no contribution to
                # search for new directions.
                continue

            max_trial_error = max(max_trial_error, numpy.linalg.norm(current_error_v))
            diagonal_inverse = numpy.ones(origonal_dimension)
            for j in range(origonal_dimension):
                # Makes sure error vectors are bounded.
                diff_lambda = self.linear_operator_diagonal[j] - trial_lambda[i]
                if numpy.abs(diff_lambda) > self.eps:
                    diagonal_inverse[j] /= diff_lambda
                else:
                    diagonal_inverse[j] /= self.eps
            diagonal_inverse_error = diagonal_inverse * current_error_v
            diagonal_inverse_trial = diagonal_inverse * trial_v[:, i]
            new_direction = -current_error_v + (trial_v[:, i] * numpy.dot(
                trial_v[:, i].conj(), diagonal_inverse_error) / numpy.dot(
                    trial_v[:, i].conj(), diagonal_inverse_trial))

            new_directions.append(new_direction)
        return new_directions, max_trial_error


class QubitDavidson(Davidson):
    """Davidson algorithm applied to a QubitOperator."""

    def __init__(self, qubit_operator, n_qubits=None, eps=1e-6):
        """
        Args:
            qubit_operator(QubitOperator): A qubit operator which is a linear
                operator as well.
            n_qubits(int): Number of qubits.
            eps(float): The max error for eigen vectors' elements during
                iterations.
        """
        super(QubitDavidson, self).__init__(
            get_linear_qubit_operator(qubit_operator, n_qubits),
            get_linear_qubit_operator_diagonal(qubit_operator, n_qubits), eps)
