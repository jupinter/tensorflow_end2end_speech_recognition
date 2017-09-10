#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Unidirectional GRU encoder."""

import tensorflow as tf


class GRU_Encoder(object):
    """Unidirectional GRU encoder.
    Args:
        num_units (int): the number of units in each layer
        num_layers (int): the number of layers
        num_classes (int): the number of classes of target labels
            (except for a blank label)
        parameter_init (float): Range of uniform distribution to initialize
            weight parameters
        bottleneck_dim (int): the dimensions of the bottleneck layer
        name (string, optional): the name of encoder
    """

    def __init__(self,
                 num_units,
                 num_layers,
                 num_classes,
                 parameter_init,
                 bottleneck_dim,
                 name='gru_encoder'):

        self.num_units = num_units
        self.num_layers = num_layers
        self.num_classes = num_classes
        self.parameter_init = parameter_init
        self.bottleneck_dim = int(bottleneck_dim) if bottleneck_dim not in [
            None, 0] else None
        self.name = name

    def __call__(self, inputs, inputs_seq_len, keep_prob_input,
                 keep_prob_hidden, keep_prob_output):
        """Construct model graph.
        Args:
            inputs: A tensor of size `[B, T, input_size]`
            inputs_seq_len:  A tensor of size `[B]`
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
        # Dropout for the input-hidden connection
        inputs = tf.nn.dropout(
            inputs, keep_prob_input, name='dropout_input')

        initializer = tf.random_uniform_initializer(
            minval=-self.parameter_init, maxval=self.parameter_init)

        # Hidden layers
        gru_list = []
        for i_layer in range(1, self.num_layers + 1, 1):
            with tf.variable_scope('gru_hidden' + str(i_layer), initializer=initializer):

                gru = tf.contrib.rnn.GRUCell(self.num_units)

                # Dropout for the hidden-hidden connections
                gru = tf.contrib.rnn.DropoutWrapper(
                    gru, output_keep_prob=keep_prob_hidden)

                gru_list.append(gru)

        # Stack multiple cells
        stacked_gru = tf.contrib.rnn.MultiRNNCell(
            gru_list, state_is_tuple=True)

        # Ignore 2nd return (the last state)
        outputs, final_state = tf.nn.dynamic_rnn(
            cell=stacked_gru,
            inputs=inputs,
            sequence_length=inputs_seq_len,
            dtype=tf.float32)

        # inputs: `[batch_size, max_time, input_size]`
        batch_size = tf.shape(inputs)[0]

        # Reshape to apply the same weights over the timesteps
        outputs = tf.reshape(outputs, shape=[-1, self.num_units])

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
            # NOTE: This may lead to bad results

            return logits, final_state
