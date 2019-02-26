# from graph.core import GridWorldScene
import ai2thor.controller
import numpy as np
import cv2

class ThorGridWorld:
    def __init__(self, maze, observations):
        self._observations = observations
        self._maze = maze

    def render(self, position, direction):
        return self._observations[position[0], position[1], direction]

    @property
    def maze(self):
        return self._maze

    @property
    def observation_shape(self):
        return self._observations.shape[-3:]

    @property
    def dtype(self):
        return np.uint8

class GridWorldReconstructor:
    def __init__(self, scene_name = 'FloorPlan28', grid_size = 0.5, env_kwargs = dict(), screen_size = (300,300,)):
        self.screen_size = screen_size
        self.grid_size = grid_size
        self.env_kwargs = env_kwargs
        self.scene_name = scene_name

    def _initialize(self):
        self._collected_positions = set()
        self._position = (0, 0)
        self._controller = ai2thor.controller.Controller()
        self._controller.start()
        self._controller.reset(self.scene_name)

        self._frames = dict()
        self._realcoordinates = dict()
        # gridSize specifies the coarseness of the grid that the agent navigates on
        self._controller.step(dict(action='Initialize', grid_size=self.grid_size, **self.env_kwargs))

    def _compute_new_position(self, original, direction):
        dir1, dir2 = original
        if direction == 0:
            return (dir1 + 1, dir2)
        elif direction == 1:
            return (dir1, dir2 + 1)
        elif direction == 2:
            return (dir1 - 1, dir2)
        else:
            return (dir1, dir2 - 1)

    def _collect_spot(self, position):
        if position in self._collected_positions:
            return

        self._collected_positions.add(position)
        print('collected '  + str(position))

        frames = [None, None, None, None]

        # Collect all four images in all directions
        for d in range(4):
            event = self._controller.step(dict(action='RotateRight'))
            frames[(1 + d) % 4] = event.frame

        self._realcoordinates[position] = event.metadata['agent']['position']
        self._frames[position] = frames

        # Collect frames in all four dimensions
        newposition = self._compute_new_position(position, 0)
        if not newposition in self._collected_positions:
            event = self._controller.step(dict(action='MoveAhead'))
            if event.metadata.get('lastActionSuccess'):
                self._collect_spot(newposition)
                event = self._controller.step(dict(action = 'MoveBack'))

        newposition = self._compute_new_position(position, 1)
        if not newposition in self._collected_positions:
            event = self._controller.step(dict(action='MoveRight'))
            if event.metadata.get('lastActionSuccess'):
                self._collect_spot(newposition)
                event = self._controller.step(dict(action = 'MoveLeft'))

        newposition = self._compute_new_position(position, 2)
        if not newposition in self._collected_positions:
            event = self._controller.step(dict(action='MoveBack'))
            if event.metadata.get('lastActionSuccess'):
                self._collect_spot(newposition)
                event = self._controller.step(dict(action = 'MoveAhead'))

        newposition = self._compute_new_position(position, 3)
        if not newposition in self._collected_positions:
            event = self._controller.step(dict(action='MoveLeft'))
            if event.metadata.get('lastActionSuccess'):
                self._collect_spot(newposition)
                event = self._controller.step(dict(action = 'MoveRight'))

    def _compile(self):
        minx = min(self._frames.keys(), default = 0, key = lambda x: x[0])[0]
        miny = min(self._frames.keys(), default = 0, key = lambda x: x[1])[1]
        maxx = max(self._frames.keys(), default = 0, key = lambda x: x[0])[0]
        maxy = max(self._frames.keys(), default = 0, key = lambda x: x[1])[1]

        size = (maxx - minx + 1, maxy - miny + 1)
        observations = np.zeros(size + (4,) + self.screen_size +(3,), dtype = np.uint8)
        grid = np.zeros(size, dtype = np.bool)
        for key, value in self._frames.items():
            for i in range(4):
                observations[key[0] - minx, key[1] - miny, i] = cv2.resize(value[i], self.screen_size)
            grid[key[0] - minx, key[1] - miny] = 1

        return ThorGridWorld(grid, observations)

    def reconstruct(self):
        self._initialize()
        self._controller.step(dict(action = 'RotateLeft'))
        self._collect_spot((0, 0))
        return self._compile()