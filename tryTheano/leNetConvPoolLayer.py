__author__ = 'jennyyuejin'


import sys
import numpy as np

import theano
import theano.tensor as T
from theano.tensor.nnet import conv
from theano.tensor.signal import downsample
from theano.tensor.signal.downsample import DownsampleFactorMax
from theano.sandbox.cuda.basic_ops import gpu_contiguous
from pylearn2.sandbox.cuda_convnet.filter_acts import FilterActs
from pylearn2.sandbox.cuda_convnet.pool import MaxPool
# theano.config.openmp = True
# theano.config.optimizer = 'None'
# theano.config.exception_verbosity='high'

sys.path.extend(['/Users/jennyyuejin/K/tryTheano'])

useNew = False


class LeNetConvPoolLayer(object):
    """Pool Layer of a convolutional network """

    def __init__(self, rng, input, filter_shape,
                 poolWidth, poolStride,
                 filterStride,
                 poolPadding = 0,
                 image_shape = None,
                 activation = T.tanh):
        """
        Allocate a LeNetConvPoolLayer with shared variable internal parameters.

        :type rng: np.random.RandomState
        :param rng: a random number generator used to initialize weights

        :type input: theano.tensor.dtensor4
        :param input: symbolic image tensor, of shape image_shape

        :type filter_shape: tuple or list of length 4
        :param filter_shape: (number of filters, num input feature maps,
                              filter height, filter width)

        :type image_shape: tuple or list of length 4
        :param image_shape: (batch size, num input feature maps,
                             image height, image width)

        :type poolWidth: int
        :param poolWidth: the downsampling (pooling) factor (assumed to be square)

        :type activation: theano.Op or function
        :param activation: Non linearity to be applied in the hidden
                           layer
        """

        assert poolWidth >= poolStride, 'Pool stride (%i) cannot be greater than pool width (%i).' % (poolStride, poolWidth)
        if image_shape is not None:
            assert image_shape[1] == filter_shape[1]
        self.input = input
        self.filterStrideFactor = filterStride

        # there are "num input feature maps * filter height * filter width" inputs to each hidden unit
        fan_in = np.prod(filter_shape[1:])

        # each unit in the lower layer receives a gradient from:
        # "num output feature maps * filter height * filter width" /
        #   pooling size
        fan_out = (filter_shape[0] * np.prod(filter_shape[2:]) /
                   poolWidth**2)

        # initialize weights with random weights
        W_bound = np.sqrt(6. / (fan_in + fan_out))

        self.W = theano.shared(
            np.asarray(
                rng.uniform(low=-W_bound, high=W_bound, size=filter_shape),
                dtype=theano.config.floatX
            ),
            borrow=True
        )

        # the bias is a 1D tensor -- one bias per output feature map
        b_values = np.zeros((filter_shape[0],), dtype=theano.config.floatX)
        self.b = theano.shared(value=b_values, borrow=True)


        if useNew:  # doesn't work yet

            input_shuffled = input.dimshuffle(1, 2, 3, 0) # bc01 to c01b
            filters_shuffled = self.W.dimshuffle(1, 2, 3, 0) # bc01 to c01b
            conv_op = FilterActs(stride=1, partial_sum=1)
            contiguous_input = gpu_contiguous(input_shuffled)
            contiguous_filters = gpu_contiguous(filters_shuffled)
            conv_out_shuffled = conv_op(contiguous_input, contiguous_filters)

            pool_op = MaxPool(ds=poolWidth, stride=poolStride)
            pooled_out_shuffled = pool_op(conv_out_shuffled)
            pooled_out = pooled_out_shuffled.dimshuffle(3, 0, 1, 2) # c01b to bc01

        else:

            # convolve input feature maps with filters
            conv_out = conv.conv2d(
                input=input,
                filters=self.W,
                filter_shape=filter_shape,
                image_shape=image_shape,
                # subsample=self.filterStrideFactor
            )


            # downsample each feature map individually, using maxpooling
            poolOp = DownsampleFactorMax(ds = [poolWidth, poolWidth],
                                st = [poolStride, poolStride],
                                padding=(poolPadding, poolPadding),
                                ignore_border=True)
            pooled_out = poolOp(conv_out)

            # pooled_out = downsample.max_pool_2d(
            #     input=conv_out,
            #     ds = [poolWidth, poolWidth],
            #     st = [poolStride, poolStride],
            #     padding=(poolPadding, poolPadding),
            #     ignore_border=True
            # )


        # add the bias term. Since the bias is a vector (1D array), we first
        # reshape it to a tensor of shape (1, n_filters, 1, 1). Each bias will
        # thus be broadcasted across mini-batches and feature map
        # width & height
        self.lin_output = pooled_out + self.b.dimshuffle('x', 0, 'x', 'x')

        self.output = self.lin_output if activation is None else activation(self.lin_output)

        # store parameters of this layer
        self.params = [self.W, self.b]

        # l1 and l2 errors
        self.L1 = T.cast(abs(self.W).sum(), theano.config.floatX)
        self.L2 = T.cast((self.W**2).sum(), theano.config.floatX)
