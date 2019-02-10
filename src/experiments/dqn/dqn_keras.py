import random
import numpy as np
import tensorflow as tf
import functools
import os, sys

import keras.backend as K

if __name__ == '__main__':
    import os,sys,inspect
    currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    parentdir = os.path.dirname(os.path.dirname(currentdir))
    sys.path.insert(0,parentdir) 

from model.model_keras import DeepQModel
from environment.environment import Environment
from train.experience import ExperienceFrame



class ExperienceReplay():
    def __init__(self, buffer_size = 50000):
        self.buffer = []
        self.buffer_size = buffer_size
    
    def add(self,experience):
        if len(self.buffer) + len(experience) >= self.buffer_size:
            self.buffer[0:(len(experience)+len(self.buffer))-self.buffer_size] = []
        self.buffer.extend(experience)
            
    def sample(self,size):
        STATE_INDICES = [0,3]
        items = random.sample(self.buffer,size)
        def convert_dict(dicts, i):
            if len(dicts) == 0:
                return {}
            else:
                return {key:np.stack([y[i][key] for y in dicts], 0) for key in dicts[0][i].keys()}
        def convert(items, i):
            if i in STATE_INDICES:
                return convert_dict(items, i)
            return np.array([x[i] for x in items])

        batch = [convert(items, i) for i in range(5)]
        return batch



def update_target_graph(main_graph, target_graph, tau):
    updated_weights = (np.array(main_graph.get_weights()) * tau) + \
        (np.array(target_graph.get_weights()) * (1 - tau))
    target_graph.set_weights(updated_weights)

class DoubleQLearning:
    def __init__(self, 
                model_fn, 
                env, 
                tau, 
                start_epsilon, 
                end_epsilon, 
                annealing_steps, 
                episode_length, 
                pre_train_steps,
                checkpoint_dir,
                update_frequency,
                num_episodes,
                num_epochs,
                gamma,
                goal,
                device,
                batch_size,
                **kwargs):
        self._env = env
        self._checkpoint_dir = checkpoint_dir
        self._episode_length = episode_length
        self._num_epochs = num_epochs
        self._pre_train_steps = pre_train_steps
        self._gamma = gamma
        self._update_frequency = update_frequency
        self._num_episodes = num_episodes
        self._batch_size = batch_size
        self._start_epsilon = start_epsilon
        self._end_epsilon = end_epsilon
        self._annealing_steps = annealing_steps
        self._device = device
        self._goal = goal
        self._tau = tau
        self._main_weights_file = self._checkpoint_dir + "/main_weights.h5" # File to save our main weights to
        self._target_weights_file = self._checkpoint_dir + "/target_weights.h5" # File to save our target weights to

    def _process_state(self, state, action = -1, reward = 0):
        return {'image': state['image'], 
            'goal': state['goal'], 
            'action_reward': ExperienceFrame.concat_action_and_reward(action, self._env.action_space.n, reward, state)}

    def run(self):
        # Reset everything
        K.clear_session()

        # Setup our Q-networks
        main_qn = DeepQModel(self._env.action_space.n, device = self._device)
        target_qn = DeepQModel(self._env.action_space.n, device = self._device)

        # Make the networks equal
        update_target_graph(main_qn.model, target_qn.model, 1)

        # Setup our experience replay
        experience_replay = ExperienceReplay()

        # We'll begin by acting complete randomly. As we gain experience and improve,
        # we will begin reducing the probability of acting randomly, and instead
        # take the actions that our Q network suggests
        prob_random = self._start_epsilon
        prob_random_drop = (self._start_epsilon - self._end_epsilon) / self._annealing_steps

        num_steps = [] # Tracks number of steps per episode
        rewards = [] # Tracks rewards per episode
        total_steps = 0 # Tracks cumulative steps taken in training

        print_every = 50 # How often to print status
        save_every = 5 # How often to save

        losses = [0] # Tracking training losses

        num_episode = 0

        # Setup path for saving
        if not os.path.exists(self._checkpoint_dir):
            os.makedirs(self._checkpoint_dir)

        if os.path.exists(self._main_weights_file):
            print("Loading main weights")
            main_qn.model.load_weights(self._main_weights_file)
        if os.path.exists(self._target_weights_file):
            print("Loading target weights")
            target_qn.model.load_weights(self._target_weights_file)

        while num_episode < self._num_episodes:

            # Create an experience replay for the current episode
            episode_buffer = ExperienceReplay()

            # Get the game state from the environment
            state = self._env.reset()
            state = self._process_state(state)

            done = False # Game is complete
            sum_rewards = 0 # Running sum of rewards in episode
            cur_step = 0 # Running sum of number of steps taken in episode

            while cur_step < self._episode_length and not done:
                cur_step += 1
                total_steps += 1

                if np.random.rand() < prob_random or \
                    num_episode < self._pre_train_steps:
                        # Act randomly based on prob_random or if we
                        # have not accumulated enough pre_train episodes
                        action = np.random.randint(self._env.action_space.n)
                else:
                    # Decide what action to take from the Q network
                    action = np.argmax(main_qn.model.predict([state['image'], state['goal'], state['action_reward']]))

                # Take the action and retrieve the next state, reward and done
                next_state, reward, done, _ = self._env.step(action)
                next_state = self._process_state(next_state, action, reward)

                # Setup the episode to be stored in the episode buffer
                episode = np.array([[state],action,reward,[next_state],done])
                episode = episode.reshape(1,-1)

                # Store the experience in the episode buffer
                episode_buffer.add(episode)

                # Update the running rewards
                sum_rewards += reward

                # Update the state
                state = next_state

            if num_episode > self._pre_train_steps:
                # Training the network

                if prob_random > self._end_epsilon:
                    # Drop the probability of a random action
                    prob_random -= prob_random_drop

                if num_episode % self._update_frequency == 0:
                    for num_epoch in range(self._num_epochs):
                        # Train batch is [[state,action,reward,next_state,done],...]
                        train_batch = experience_replay.sample(self._batch_size)

                        # Separate the batch into its components
                        train_state, train_action, train_reward, \
                            train_next_state, train_done = train_batch
                            
                        # Convert the action array into an array of ints so they can be used for indexing
                        train_action = train_action.astype(np.int)

                        # Our predictions (actions to take) from the main Q network
                        target_q = target_qn.model.predict([
                            train_next_state['image'],
                            train_next_state['goal'], 
                            train_next_state['action_reward']])
                        
                        # The Q values from our target network from the next state
                        target_q_next_state = main_qn.model.predict([
                            train_next_state['image'],
                            train_next_state['goal'], 
                            train_next_state['action_reward']])

                        train_next_state_action = np.argmax(target_q_next_state,axis=1)
                        train_next_state_action = train_next_state_action.astype(np.int)
                        
                        # Tells us whether game over or not
                        # We will multiply our rewards by this value
                        # to ensure we don't train on the last move
                        train_gameover = train_done == 0

                        # Q value of the next state based on action
                        train_next_state_values = target_q_next_state[:, train_next_state_action]

                        # Reward from the action chosen in the train batch
                        actual_reward = train_reward + (self._gamma * train_next_state_values * train_gameover)
                        target_q[:, train_action] = actual_reward
                        
                        # Train the main model
                        loss = main_qn.model.train_on_batch([train_state['image'],
                            train_state['goal'],
                            train_state['action_reward']], target_q)
                        losses.append(loss)
                        
                    # Update the target model with values from the main model
                    update_target_graph(main_qn.model, target_qn.model, self._tau)

                    if (num_episode + 1) % save_every == 0:
                        # Save the model
                        main_qn.model.save_weights(self._main_weights_file)
                        target_qn.model.save_weights(self._target_weights_file)
            

            # Increment the episode
            num_episode += 1

            experience_replay.add(episode_buffer.buffer)
            num_steps.append(cur_step)
            rewards.append(sum_rewards)
                
            if num_episode % print_every == 0:
                # Print progress
                mean_loss = np.mean(losses[-(print_every * self._num_epochs):])

                print("Num episode: {} Mean reward: {:0.4f} Prob random: {:0.4f}, Loss: {:0.04f}".format(
                    num_episode, np.mean(rewards[-print_every:]), prob_random, mean_loss))
                if self._goal != None and np.mean(rewards[-print_every:]) >= self._goal:
                    print("Training complete!")
                    break

def get_options():
    tf.app.flags.DEFINE_integer('batch_size', 32, 'How many experiences to use for each training step.')
    tf.app.flags.DEFINE_integer('update_frequency', 4, 'How often to perform a training step.')
    tf.app.flags.DEFINE_float('gamma', .99, 'Discount factor on the target Q-values')
    tf.app.flags.DEFINE_float('start_epsilon', 1, 'Starting chance of random action')
    tf.app.flags.DEFINE_float('end_epsilon', 0.1, 'Final chance of random action')
    tf.app.flags.DEFINE_integer('annealing_steps', 10000, 'How many steps of training to reduce startE to endE.')
    tf.app.flags.DEFINE_integer('num_episodes', 10000, 'How many episodes of game environment to train network with.')
    tf.app.flags.DEFINE_integer('num_epochs', 20, 'How many epochs to train.')
    tf.app.flags.DEFINE_integer('pre_train_steps', 10000, 'How many steps of random actions before training begins.')
    tf.app.flags.DEFINE_integer('episode_length', 50, 'The max allowed length of our episode.')
    tf.app.flags.DEFINE_string("checkpoint_dir", "./checkpoints", "checkpoint directory")
    tf.app.flags.DEFINE_float('tau', 0.001, 'Rate to update target network toward primary network')
    tf.app.flags.DEFINE_float('goal', None, 'Target reward (-1) if none')
    return tf.app.flags.FLAGS

class Application:
    def __init__(self, flags):
        self._flags = flags
        pass

    def run(self):
        
        device = "/gpu:0"
        env = Environment.create_environment('maze', 'gr')

        model_fn = lambda name, device: DeepQModel(
                env.get_action_size(),
                0,
                thread_index = name, # -1 for global
                use_lstm = False,
                use_pixel_change = False,
                use_value_replay = False,
                use_reward_prediction = False,
                use_deepq_network = True,
                use_goal_input = env.can_use_goal(),              
                pixel_change_lambda = .05,
                entropy_beta = .001,
                device = device,
            )

        learning = DoubleQLearning(model_fn, env.get_env(), device = device, **self._flags.flag_values_dict())
        learning.run()

if __name__ == '__main__':
    flags = get_options()
    tf.app.run(lambda _: Application(flags).run())