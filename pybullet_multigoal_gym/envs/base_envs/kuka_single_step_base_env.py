import os
import numpy as np
from pybullet_multigoal_gym.envs.base_envs.base_env import BaseBulletMGEnv
from pybullet_multigoal_gym.robots.kuka import Kuka


class KukaBulletMGEnv(BaseBulletMGEnv):
    """
    Base class for the OpenAI multi-goal manipulation tasks with a Kuka iiwa 14 robot
    """

    def __init__(self, render=True, binary_reward=True,
                 image_observation=False, goal_image=False, depth_image=False, visualize_target=True,
                 camera_setup=None, observation_cam_id=None, goal_cam_id=0,
                 gripper_type='parallel_jaw', table_type='table', obj_range=0.15, target_range=0.15,
                 target_in_the_air=True, end_effector_start_on_table=False,
                 distance_threshold=0.05, joint_control=False, grasping=False, has_obj=False):
        if observation_cam_id is None:
            observation_cam_id = [0]
        self.binary_reward = binary_reward
        self.image_observation = image_observation
        self.goal_image = goal_image
        if depth_image:
            self.render_mode = 'rgbd_array'
        else:
            self.render_mode = 'rgb_array'
        self.visualize_target = visualize_target
        self.observation_cam_id = observation_cam_id
        self.goal_cam_id = goal_cam_id

        self.table_type = table_type
        assert self.table_type in ['table', 'long_table']
        self.target_in_the_air = target_in_the_air
        self.distance_threshold = distance_threshold
        self.joint_control = joint_control
        self.grasping = grasping
        self.has_obj = has_obj
        self.obj_range = obj_range
        self.target_range = target_range

        self.object_assets_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "objects")
        self.objects_urdf_loaded = False
        self.object_bodies = {
            'table': None,
            'block': None,
            'target': None
        }
        self.object_initial_pos = {
            'table': [-0.52, 0.0, 0.08, 0.0, 0.0, 0.0, 1.0],
            'block': [-0.52, 0.0, 0.175, 0.0, 0.0, 0.0, 1.0],
            'target': [-0.52, 0.0, 0.186, 0.0, 0.0, 0.0, 1.0]
        }
        if self.table_type == 'long_table':
            self.object_initial_pos['table'][0] = -0.70
            self.object_initial_pos['block'][0] = -0.50
            self.object_initial_pos['block'][2] = 0.170

        self.desired_goal = None
        self.desired_goal_image = None

        robot = Kuka(grasping=grasping,
                     joint_control=joint_control,
                     gripper_type=gripper_type,
                     end_effector_start_on_table=end_effector_start_on_table,
                     obj_range=self.obj_range, target_range=self.target_range)
        if self.table_type == 'long_table':
            # target range for slide task
            robot.target_bound_lower[0] -= 0.4
            robot.target_bound_upper[0] -= 0.4

        BaseBulletMGEnv.__init__(self, robot=robot, render=render,
                                 image_observation=image_observation, goal_image=goal_image,
                                 camera_setup=camera_setup,
                                 seed=0, timestep=0.002, frame_skip=20)

    def _task_reset(self, test=False):
        if not self.objects_urdf_loaded:
            # don't reload object urdf
            self.objects_urdf_loaded = True
            self.object_bodies['table'] = self._p.loadURDF(
                os.path.join(self.object_assets_path, self.table_type + ".urdf"),
                basePosition=self.object_initial_pos['table'][:3],
                baseOrientation=self.object_initial_pos['table'][3:])
            self.object_bodies['target'] = self._p.loadURDF(
                os.path.join(self.object_assets_path, "target.urdf"),
                basePosition=self.object_initial_pos['target'][:3],
                baseOrientation=self.object_initial_pos['target'][3:])
            if self.has_obj:
                if self.table_type == 'long_table':
                    self.object_bodies['block'] = self._p.loadURDF(
                        os.path.join(self.object_assets_path, "cylinder_bulk.urdf"),
                        basePosition=self.object_initial_pos['block'][:3],
                        baseOrientation=self.object_initial_pos['block'][3:])
                else:
                    self.object_bodies['block'] = self._p.loadURDF(
                        os.path.join(self.object_assets_path, "block.urdf"),
                        basePosition=self.object_initial_pos['block'][:3],
                        baseOrientation=self.object_initial_pos['block'][3:])
            if not self.visualize_target:
                self.set_object_pose(self.object_bodies['target'],
                                     [0.0, 0.0, -3.0],
                                     self.object_initial_pos['target'][3:])

        # randomize object positions
        object_xyz_1 = None
        if self.has_obj:
            end_effector_tip_initial_position = self.robot.end_effector_tip_initial_position.copy()
            object_xy_1 = end_effector_tip_initial_position[:2]
            while np.linalg.norm(object_xy_1 - end_effector_tip_initial_position[:2]) < 0.1:
                object_xy_1 = self.np_random.uniform(self.robot.object_bound_lower[:-1],
                                                     self.robot.object_bound_upper[:-1])

            object_xyz_1 = np.append(object_xy_1, self.object_initial_pos['block'][2])
            self.set_object_pose(self.object_bodies['block'],
                                 object_xyz_1,
                                 self.object_initial_pos['block'][3:])

        # generate goals & images
        self._generate_goal(current_obj_pos=object_xyz_1)
        if self.goal_image:
            self._generate_goal_image(current_obj_pos=object_xyz_1)

    def _generate_goal(self, current_obj_pos=None):
        if current_obj_pos is None:
            # generate a goal around the gripper if no object is involved
            center = self.robot.end_effector_tip_initial_position.copy()
        else:
            center = current_obj_pos

        # generate the 3DoF goal within a 3D bounding box such that,
        #       it is at least 0.02m away from the gripper or the object
        while True:
            self.desired_goal = self.np_random.uniform(self.robot.target_bound_lower,
                                                       self.robot.target_bound_upper)
            if np.linalg.norm(self.desired_goal - center) > 0.1:
                break

        if not self.target_in_the_air:
            self.desired_goal[2] = self.object_initial_pos['block'][2]
        elif self.grasping:
            # with .5 probability, set the pick-and-place target on the table
            if self.np_random.uniform(0, 1) >= 0.5:
                self.desired_goal[2] = self.object_initial_pos['block'][2]

        if self.visualize_target:
            self.set_object_pose(self.object_bodies['target'],
                                 self.desired_goal,
                                 self.object_initial_pos['target'][3:])

    def _generate_goal_image(self, current_obj_pos=None):
        if current_obj_pos is None:
            # no object cases
            target_gripper_pos = self.desired_goal.copy()
            target_kuka_joint_pos = self.robot.compute_ik(target_gripper_pos)
            self.robot.set_kuka_joint_state(target_kuka_joint_pos)
            self.desired_goal_image = self.render(mode=self.render_mode, camera_id=self.goal_cam_id)
            self.robot.set_kuka_joint_state(self.robot.kuka_rest_pose, np.zeros(7))
        elif not self.grasping:
            # Push task
            original_obj_pos = current_obj_pos.copy()
            target_obj_pos = self.desired_goal.copy()
            self.set_object_pose(self.object_bodies['block'],
                                 target_obj_pos,
                                 self.object_initial_pos['block'][3:])
            self.desired_goal_image = self.render(mode=self.render_mode, camera_id=self.goal_cam_id)
            self.set_object_pose(self.object_bodies['block'],
                                 original_obj_pos,
                                 self.object_initial_pos['block'][3:])
        else:
            # PickAndPlace task
            self.robot.set_finger_joint_state(self.robot.gripper_grasp_block_state)
            target_gripper_pos = self.desired_goal.copy()
            target_kuka_joint_pos = self.robot.compute_ik(target_gripper_pos)
            self.robot.set_kuka_joint_state(target_kuka_joint_pos)

            original_obj_pos = current_obj_pos.copy()
            target_obj_pos = self.desired_goal.copy()
            self.set_object_pose(self.object_bodies['block'],
                                 target_obj_pos,
                                 self.object_initial_pos['block'][3:])

            self.desired_goal_image = self.render(mode=self.render_mode, camera_id=self.goal_cam_id)

            self.set_object_pose(self.object_bodies['block'],
                                 original_obj_pos,
                                 self.object_initial_pos['block'][3:])
            self.robot.set_kuka_joint_state(self.robot.kuka_rest_pose, np.zeros(7))
            self.robot.set_finger_joint_state(self.robot.gripper_abs_joint_limit)

    def _step_callback(self):
        pass

    def _get_obs(self):
        # robot state contains gripper xyz coordinates, orientation (and finger width)
        gripper_xyz, gripper_rpy, gripper_finger_closeness, gripper_vel_xyz, gripper_vel_rpy, gripper_finger_vel, joint_poses = self.robot.calc_robot_state()
        assert self.desired_goal is not None
        policy_state = state = gripper_xyz
        achieved_goal = gripper_xyz.copy()
        if self.has_obj:
            block_xyz, _ = self._p.getBasePositionAndOrientation(self.object_bodies['block'])
            block_rel_xyz = gripper_xyz - np.array(block_xyz)
            block_vel_xyz, block_vel_rpy = self._p.getBaseVelocity(self.object_bodies['block'])
            block_rel_vel_xyz = gripper_vel_xyz - np.array(block_vel_xyz)
            block_rel_vel_rpy = gripper_vel_rpy - np.array(block_vel_rpy)
            achieved_goal = np.array(block_xyz).copy()
            # the HER paper use different state observations for the policy and critic network
            # critic further takes the velocities as input
            state = np.concatenate((gripper_xyz, block_xyz, gripper_finger_closeness, block_rel_xyz,
                                    gripper_vel_xyz, gripper_finger_vel, block_rel_vel_xyz, block_rel_vel_rpy))
            policy_state = np.concatenate((gripper_xyz, gripper_finger_closeness, block_rel_xyz))
        else:
            assert not self.grasping, "grasping should not be true when there is no objects"

        if self.joint_control:
            state = np.concatenate((joint_poses, state))
            policy_state = np.concatenate((joint_poses, policy_state))

        obs_dict = {'state': state.copy(),
                    'policy_state': policy_state.copy(),
                    'achieved_goal': achieved_goal.copy(),
                    'desired_goal': self.desired_goal.copy()}
        if self.image_observation:
            images = []
            for cam_id in self.observation_cam_id:
                images.append(self.render(mode=self.render_mode, camera_id=cam_id))
            obs_dict['state'] = images[0].copy()
            obs_dict['images'] = images
            obs_dict.update({'state': state.copy()})
            if self.goal_image:
                achieved_goal_img = self.render(mode=self.render_mode, camera_id=self.goal_cam_id)
                obs_dict.update({
                    'achieved_goal_img': achieved_goal_img.copy(),
                    'desired_goal_img': self.desired_goal_image.copy(),
                })
        return obs_dict

    def _compute_reward(self, achieved_goal, desired_goal):
        assert achieved_goal.shape == desired_goal.shape
        d = np.linalg.norm(achieved_goal - desired_goal, axis=-1)
        not_achieved = (d > self.distance_threshold)
        if self.binary_reward:
            return -not_achieved.astype(np.float32), ~not_achieved
        else:
            return -d, ~not_achieved

    def set_object_pose(self, body_id, position, orientation=None):
        if orientation is None:
            orientation = self.object_initial_pos['table'][3:]
        self._p.resetBasePositionAndOrientation(body_id, position, orientation)
