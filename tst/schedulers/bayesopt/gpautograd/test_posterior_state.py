# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
import numpy
import autograd.numpy as anp
import pytest

from syne_tune.optimizer.schedulers.searchers.bayesopt.gpautograd.posterior_state import (
    IncrementalUpdateGPPosteriorState,
    GaussProcPosteriorState,
)
from syne_tune.optimizer.schedulers.searchers.bayesopt.gpautograd.gp_regression import (
    GaussianProcessRegression,
)
from syne_tune.optimizer.schedulers.searchers.bayesopt.gpautograd.kernel import Matern52


@pytest.mark.timeout(5)
def test_incremental_update():
    def f(x):
        return anp.sin(x) / x

    numpy.random.seed(298424)
    std_noise = 0.01

    # Sample data
    features_list = []
    targets_list = []
    num_incr_list = []
    for rep in range(10):
        num_train = anp.random.randint(low=5, high=15)
        num_incr = anp.random.randint(low=1, high=7)
        num_incr_list.append(num_incr)
        sizes = [num_train, num_incr]
        features = []
        targets = []
        for sz in sizes:
            feats = anp.random.uniform(low=-1.0, high=1.0, size=sz).reshape((-1, 1))
            features.append(feats)
            targs = f(feats)
            targs += anp.random.normal(0.0, std_noise, size=targs.shape)
            targets.append(targs)

        features_list.append(features)
        targets_list.append(targets)

    for rep in range(10):
        model = GaussianProcessRegression(kernel=Matern52(dimension=1))
        features = features_list[rep]
        targets = targets_list[rep]
        # Posterior state by incremental updating
        data = {"features": features[0], "targets": targets[0]}
        model.fit(data)
        noise_variance_1 = model.likelihood.get_noise_variance()
        state_incr = IncrementalUpdateGPPosteriorState(
            **data,
            mean=model.likelihood.mean,
            kernel=model.likelihood.kernel,
            noise_variance=model.likelihood.get_noise_variance(as_ndarray=True),
        )
        num_incr = num_incr_list[rep]
        for i in range(num_incr):
            state_incr = state_incr.update(
                features[1][i].reshape((1, -1)), targets[1][i].reshape((1, -1))
            )
        noise_variance_2 = state_incr.noise_variance[0]
        # Posterior state by direct computation
        state_comp = GaussProcPosteriorState(
            features=anp.concatenate(features, axis=0),
            targets=anp.concatenate(targets, axis=0),
            mean=model.likelihood.mean,
            kernel=model.likelihood.kernel,
            noise_variance=state_incr.noise_variance,
        )
        # Compare them
        assert (
            noise_variance_1 == noise_variance_2
        ), "noise_variance_1 = {} != {} = noise_variance_2".format(
            noise_variance_1, noise_variance_2
        )
        chol_fact_incr = state_incr.chol_fact
        chol_fact_comp = state_comp.chol_fact
        numpy.testing.assert_almost_equal(chol_fact_incr, chol_fact_comp, decimal=2)
        pred_mat_incr = state_incr.pred_mat
        pred_mat_comp = state_comp.pred_mat
        numpy.testing.assert_almost_equal(pred_mat_incr, pred_mat_comp, decimal=2)


if __name__ == "__main__":
    test_incremental_update()
