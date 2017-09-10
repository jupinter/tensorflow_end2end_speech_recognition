#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""VGG + bidirectional LSTM encoder."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import tensorflow as tf


class VGG_BLSTM_Encoder(object):
    """VGG + bidirectional LSTM encoder.
    Args:
        input_size (int):
        num_units (int): the number of units in each layer
        num_layers (int): the number of layers
        num_classes (int): the number of classes of target labels
            (except for a blank label)
        lstm_impl (string): BasicLSTMCell or LSTMCell or LSTMBlockCell or
            LSTMBlockFusedCell.
            Choose the background implementation of tensorflow.
            Default is LSTMBlockCell (the fastest implementation).
        use_peephole (bool): if True, use peephole
        parameter_init (float): Range of uniform distribution to initialize
            weight parameters
        clip_activation (float): Range of activation clipping (> 0)
        num_proj (int): the number of nodes in recurrent projection layer
        bottleneck_dim (int): the dimensions of the bottleneck layer
        name (string, optional): the name of encoder
    """

    def __init__(self,
                 input_size,
                 num_units,
                 num_layers,
                 num_classes,
                 lstm_impl,
                 use_peephole,
                 splice,
                 parameter_init,
                 clip_activation,
                 num_proj,
                 bottleneck_dim,
                 name='vgg_blstm_encoder'):

        self.input_size = input_size
        self.num_units = num_units
        self.num_layers = num_layers
        self.num_classes = num_classes
        self.lstm_impl = lstm_impl
        self.use_peephole = use_peephole
        self.splice = splice
        self.parameter_init = parameter_init
        self.clip_activation = clip_activation
        if lstm_impl != 'LSTMCell':
            self.num_proj = None
        elif num_proj not in [None, 0]:
            self.num_proj = int(num_proj)
        else:
            self.num_proj = None
        self.bottleneck_dim = int(bottleneck_dim) if bottleneck_dim not in [
            None, 0] else None
        self.name = name

    def __call__(self, inputs, inputs_seq_len, keep_prob_input,
                 keep_prob_hidden, keep_prob_output):
        """Construct model graph.
        Args:
            inputs: A tensor of size `[B, T, input_size]`
            inputs_seq_len: A tensor of size `[B]`
            keep_prob_input (float): A probability to keep nodes in the
                input-hidden connection
            keep_prob_hidden (float): A probability to keep nodes in the
                hidden-hidden connection
            keep_prob_output (float): A probability to keep nodes in the
                hidden-output connection
        Returns:
            logits: A tensor of size `[T, B, num_classes]`
            final_state: A final hidden state of the encoder
        """
        # TODO: add lstm_impl

        # inputs: 3D tensor `[batch_size, max_time, input_size * splice]`
        batch_size = tf.shape(inputs)[0]
        max_time = tf.shape(inputs)[1]

        # Reshape to 4D tensor `[batch_size, max_time, input_size, splice]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, self.input_size, self.splice])

        # Reshape to 5D tensor
        # `[batch_size, max_time, input_size / 3, 3 (+Δ, ΔΔ), splice]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, int(self.input_size / 3), 3, self.splice])

        # Reshape to 4D tensor
        # `[batch_size * max_time, input_size / 3, splice, 3]`
        inputs = tf.transpose(inputs, (0, 1, 2, 4, 3))
        inputs = tf.reshape(
            inputs, shape=[batch_size * max_time, int(self.input_size / 3), self.splice, 3])

        with tf.name_scope('VGG1'):
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 3, 64],
                                      name='conv1')
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 64, 64],
                                      name='conv2')
            inputs = self._max_pool(inputs, name='pool')
            # TODO: try batch normalization

        with tf.name_scope('VGG2'):
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 64, 128],
                                      name='conv1')
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 128, 128],
                                      name='conv2')
            inputs = self._max_pool(inputs, name='pool')
            # TODO: try batch normalization

        # Reshape to 5D tensor `[batch_size, max_time, new_h, new_w, 128]`
        new_h = math.ceil(self.input_size / 3 / 4)  # expected to be 11 ro 10
        new_w = math.ceil(self.splice / 4)  # expected to be 3
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, new_h, new_w, 128])

        # Reshape to 3D tensor `[batch_size, max_time, new_h * new_w * 128]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, new_h * new_w * 128])

        # Insert linear layer to recude CNN's output demention
        # from new_h * new_w * 128 to 256
        with tf.name_scope('linear'):
            inputs = tf.contrib.layers.fully_connected(
                inputs=inputs,
                num_outputs=256,
                activation_fn=None,
                scope='linear')

        # Dropout for the VGG-output-hidden connection
        outputs = tf.nn.dropout(inputs,
                                keep_prob_input,
                                name='dropout_input')

        initializer = tf.random_uniform_initializer(
            minval=-self.parameter_init,
            maxval=self.parameter_init)

        # Hidden layers
        for i_layer in range(1, self.num_layers + 1, 1):
            with tf.variable_scope('blstm_hidden' + str(i_layer),
                                   initializer=initializer) as scope:

                if self.lstm_impl == 'BasicLSTMCell':
                    lstm_fw = tf.contrib.rnn.BasicLSTMCell(
                        self.num_units,
                        forget_bias=1.0,
                        state_is_tuple=True,
                        activation=tf.tanh)
                    lstm_bw = tf.contrib.rnn.BasicLSTMCell(
                        self.num_units,
                        forget_bias=1.0,
                        state_is_tuple=True,
                        activation=tf.tanh)

                elif self.lstm_impl == 'LSTMCell':
                    lstm_fw = tf.contrib.rnn.LSTMCell(
                        self.num_units,
                        use_peepholes=self.use_peephole,
                        cell_clip=self.clip_activation,
                        num_proj=self.num_proj,
                        forget_bias=1.0,
                        state_is_tuple=True)
                    lstm_bw = tf.contrib.rnn.LSTMCell(
                        self.num_units,
                        use_peepholes=self.use_peephole,
                        cell_clip=self.clip_activation,
                        num_proj=self.num_proj,
                        forget_bias=1.0,
                        state_is_tuple=True)

                elif self.lstm_impl == 'LSTMBlockCell':
                    # NOTE: This should be faster than tf.contrib.rnn.LSTMCell
                    lstm_fw = tf.contrib.rnn.LSTMBlockCell(
                        self.num_units,
                        forget_bias=1.0,
                        # clip_cell=True,
                        use_peephole=self.use_peephole)
                    lstm_bw = tf.contrib.rnn.LSTMBlockCell(
                        self.num_units,
                        forget_bias=1.0,
                        # clip_cell=True,
                        use_peephole=self.use_peephole)
                    # TODO: cell clipping (update for rc1.3)

                elif self.lstm_impl == 'LSTMBlockFusedCell':
                    raise NotImplementedError

                    # NOTE: This should be faster than
                    tf.contrib.rnn.LSTMBlockFusedCell
                    lstm_fw = tf.contrib.rnn.LSTMBlockFusedCell(
                        self.num_units,
                        forget_bias=1.0,
                        # clip_cell=True,
                        use_peephole=self.use_peephole)
                    lstm_bw = tf.contrib.rnn.LSTMBlockFusedCell(
                        self.num_units,
                        forget_bias=1.0,
                        # clip_cell=True,
                        use_peephole=self.use_peephole)
                    # TODO: cell clipping (update for rc1.3)

                else:
                    raise IndexError(
                        'lstm_impl is "BasicLSTMCell" or "LSTMCell" or "LSTMBlockCell" or "LSTMBlockFusedCell".')

                # Dropout for the hidden-hidden connections
                lstm_fw = tf.contrib.rnn.DropoutWrapper(
                    lstm_fw, output_keep_prob=keep_prob_hidden)
                lstm_bw = tf.contrib.rnn.DropoutWrapper(
                    lstm_bw, output_keep_prob=keep_prob_hidden)

                # _init_state_fw = lstm_fw.zero_state(self.batch_size,
                #                                     tf.float32)
                # _init_state_bw = lstm_bw.zero_state(self.batch_size,
                #                                     tf.float32)
                # initial_state_fw=_init_state_fw,
                # initial_state_bw=_init_state_bw,

                # Ignore 2nd return (the last state)
                (outputs_fw, outputs_bw), final_state = tf.nn.bidirectional_dynamic_rnn(
                    cell_fw=lstm_fw,
                    cell_bw=lstm_bw,
                    inputs=outputs,
                    sequence_length=inputs_seq_len,
                    dtype=tf.float32,
                    scope=scope)

                outputs = tf.concat(axis=2, values=[outputs_fw, outputs_bw])

        # Reshape to apply the same weights over the timesteps
        if self.num_proj is None:
            outputs = tf.reshape(outputs, shape=[-1, self.num_units * 2])
        else:
            outputs = tf.reshape(outputs, shape=[-1, self.num_proj * 2])

        if self.bottleneck_dim is not None and self.bottleneck_dim != 0:
            with tf.name_scope('bottleneck'):
                outputs = tf.contrib.layers.fully_connected(
                    outputs, self.bottleneck_dim,
                    activation_fn=tf.nn.relu,
                    weights_initializer=tf.truncated_normal_initializer(
                        stddev=0.1),
                    biases_initializer=tf.zeros_initializer(),
                    scope='bottleneck')

                # Dropout for the hidden-output connections
                outputs = tf.nn.dropout(
                    outputs, keep_prob_output, name='dropout_output_bottle')

        with tf.name_scope('output'):
            logits_2d = tf.contrib.layers.fully_connected(
                outputs, self.num_classes,
                activation_fn=None,
                weights_initializer=tf.truncated_normal_initializer(
                    stddev=0.1),
                biases_initializer=tf.zeros_initializer(),
                scope='output')

            # Reshape back to the original shape
            logits = tf.reshape(
                logits_2d, shape=[batch_size, -1, self.num_classes])

            # Convert to time-major: `[max_time, batch_size, num_classes]'
            logits = tf.transpose(logits, (1, 0, 2))

            # Dropout for the hidden-output connections
            logits = tf.nn.dropout(
                logits, keep_prob_output, name='dropout_output')

            return logits, final_state

    def _max_pool(self, bottom, name):
        """A max pooling layer.
        Args:
            bottom: A tensor of size `[B * T, H, W, C]`
            name (string): A layer name
        Returns:
            A tensor of size `[B * T, H / 2, W / 2, C]`
        """
        return tf.nn.max_pool(
            bottom,
            ksize=[1, 2, 2, 1],  # original
            # ksize=[1, 3, 3, 1],
            strides=[1, 2, 2, 1],
            padding='SAME', name=name)

    def _conv_layer(self, bottom, filter_shape, name):
        """A convolutional layer
        Args:
            bottom: A tensor of size `[B * T, H, W, C]`
            filter_shape: A list of
                `[height, width, input_channel, output_channel]`
            name (string): A layer name
        Returns:
            outputs: A tensor of size `[B * T, H, W, output_channel]`
        """
        with tf.variable_scope(name):
            W = tf.Variable(tf.truncated_normal(shape=filter_shape,
                                                stddev=self.parameter_init),
                            name='weight')
            b = tf.Variable(tf.zeros(shape=filter_shape[-1]),
                            name='bias')
            conv_bottom = tf.nn.conv2d(bottom, W,
                                       strides=[1, 1, 1, 1],
                                       padding='SAME')
            outputs = tf.nn.bias_add(conv_bottom, b)
            return tf.nn.relu(outputs)
