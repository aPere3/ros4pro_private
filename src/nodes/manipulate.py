#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from moveit_commander import roscpp_initialize
from moveit_commander.planning_scene_interface import PlanningSceneInterface
from moveit_commander.move_group import MoveGroupCommander
from intera_interface.gripper import Gripper
from intera_interface.camera import Cameras
from ros4pro.srv import VisionPredict, VisionPredictRequest
from ros4pro.transformations import multiply_transform, list_to_pose2, pose_to_list2, list_to_pose_stamped2
from sensor_msgs.msg import Image
from tf import TransformBroadcaster, TransformListener

class ManipulateNode(object):
    MIN_FRACTION = 0.8     # Minimum percentage of points successfully computed to initiate a cartesian trajectory (%)
    JOINT_JUMP = 5         # Authorized sum of joint angle differences between 2 cartesian points (rad)
    CART_RESOLUTION = .001 # Resolution between 2 cartesian points (m)
    CUBE_HEIGHT = 0.05     # Height of a cube to be grasped
    FEEDER_HEIGHT = 0.36 - 0.13     # Assumption of the height of the feeder minus the height of the palette
    Z_DIST_CAMERA_TO_FEEDER = 0.25  # Assumption of the z distance between the camera and the feeder

    def __init__(self):
        rospy.init_node("manipulate_sawyer")
        joint_state_topic = ['joint_states:=/robot/joint_states']
        roscpp_initialize(joint_state_topic)
        
        self.tfb = TransformBroadcaster()
        self.tfl = TransformListener()
        self.gripper = Gripper()
        self.commander = MoveGroupCommander("right_arm")
        self.camera = Cameras()
        self.scene = PlanningSceneInterface()
        self.image_camera = None
        rospy.Subscriber("/io/internal_camera/right_hand_camera/image_rect", Image, self._cb_image)

    def _cb_image(self, msg):
        self.image_camera = msg

    def scan(self):
        # Go to the scan position in joint space and wait 4 seconds for the arm to be steady
        scan_joints = [-1.2787919921875, -2.0237236328125, 2.8065361328125, 1.5006123046875, 0.1141875, -0.3843193359375, 3.331451171875]
        self.commander.set_joint_value_target(scan_joints)
        success = self.commander.go()
        rospy.sleep(4)

        # Briefly enable light flashing and send image to the vision server to see if there's some cube in there
        self.camera.set_cognex_strobe(True)
        rospy.sleep(0.1)
        self.camera.set_cognex_strobe(False)
        rospy.sleep(1)
        predict = rospy.ServiceProxy('ros4pro/vision/predict', VisionPredict)
        response = predict.call(VisionPredictRequest(image=self.image_camera))
             
        # For each found cube, compute and return its picking pose as well as its bin label 1 or 2 
        cubes = []
        for i, label_msg in enumerate(response.label):
            label = label_msg.data
            # Scale CUBE(x, y) from pixels to meters wrt right_hand_camera frame
            x = (response.x_center[i].data - 752/2)*0.310/752   
            y = (response.y_center[i].data - 480/2)*0.195/480
            z = self.Z_DIST_CAMERA_TO_FEEDER - self.CUBE_HEIGHT
            rospy.loginfo("Found cube {} with label {} at position {} wrt right_hand_camera".format(i, label, (x, y, z)))

            camera_T_cube = [[x, y, z], [0, 0, 0, 1]]
            self.tfb.sendTransform(camera_T_cube[0], camera_T_cube[1], rospy.Time.now(), "cube{}".format(i), "right_hand_camera")
            cube_T_gripper = [[0, 0, -z], [0, 0, -1, 0]]
            base_T_camera = self.tfl.lookupTransform("base", "right_hand_camera", rospy.Time(0))
            base_T_cube = multiply_transform(base_T_camera, camera_T_cube)
            self.tfb.sendTransform(base_T_cube[0], base_T_cube[1], rospy.Time.now(), "here","base")
            cubes.append((base_T_cube, label))
        return cubes
    
    def grasp(self, pose_grasp, z_approach_distance=0.18):
        self.gripper.open()

        # Go to approach pose
        pose_approach = [[pose_grasp[0][0], pose_grasp[0][1], pose_grasp[0][2] + z_approach_distance], pose_grasp[1]]      
        self.commander.set_pose_target(pose_approach[0] + pose_approach[1])
        success = self.commander.go()
        if not success:
            rospy.logerr("Can't find a valid path to approach pose")
            return False

        # Go to grasp pose
        grasp, fraction = self.commander.compute_cartesian_path(map(list_to_pose2, [pose_approach, pose_grasp]), self.CART_RESOLUTION, self.JOINT_JUMP)
        
        if fraction < self.MIN_FRACTION:
            rospy.logerr("Can't compute a valid path to grasp")
            return False

        self.commander.execute(grasp)
        self.gripper.close()

        # Go to retreat
        retreat, fraction = self.commander.compute_cartesian_path(map(list_to_pose2, [pose_grasp, pose_approach]), self.CART_RESOLUTION, self.JOINT_JUMP)

        if fraction < self.MIN_FRACTION:
            rospy.logerr("Can't compute a valid path to release")
            return False

        rospy.loginfo("{}% of success".format(int(fraction*100)))
        self.commander.execute(retreat)

        # Check if object has been grasped
        rospy.sleep(1)
        if not self.gripper.is_gripping():
            rospy.loginfo("Object hasn't been grasped, releasing")
            self.gripper.open()
            return False
        return True

    def place(self, pose_place):
        # Go to approach pose
        self.commander.set_pose_target(pose_place[0] + pose_place[1])
        success = self.commander.go()
        self.gripper.open()
        if not success:
            rospy.logerr("Can't find a valid path to place pose")
            return False

        return True

    def run(self):
        # Main function: actual behaviour of the robot
        rospy.sleep(1)
        self.scene.add_box("ground", list_to_pose_stamped2([[0, 0, 0], [0, 0, 0, 1]]), (0.65, 0.80, 0.01))
        self.scene.add_box("feeder", list_to_pose_stamped2([[-0.1, 0.57, 0.1], [0, 0, 0, 1]]), (0.8, 0.34, 0.37))
        rospy.sleep(1)

        while not rospy.is_shutdown():
            rospy.loginfo("Scanning the feeder area...")
            cubes = self.scan()
            
            for cube, label in cubes:
                if not rospy.is_shutdown():
                    rospy.loginfo("Grasping the found cube...")
                    grasped = self.grasp(cube)

                    if grasped:
                        rospy.loginfo("Grasp is a success! Placing the cube in bin {}".format(label))
                        self.place([[0.411, -0.028, 0.208], [0.707, 0.707, 0, 0]])
            rospy.sleep(1)

if __name__ == '__main__':
    ManipulateNode().run()