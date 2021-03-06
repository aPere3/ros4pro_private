# Some handy transformations not in tf.transformations

from numpy import dot, array
from moveit_commander.conversions import list_to_pose, list_to_pose_stamped, pose_to_list
import tf.transformations

def quat_rotate(rotation, vector):
    """
    Rotate a vector according to a quaternion. Equivalent to the C++ method tf::quatRotate
    :param rotation: the rotation
    :param vector: the vector to rotate
    :return: the rotated vector
    """
    def quat_mult_point(q, w):
        return (q[3] * w[0] + q[1] * w[2] - q[2] * w[1],
                q[3] * w[1] + q[2] * w[0] - q[0] * w[2],
                q[3] * w[2] + q[0] * w[1] - q[1] * w[0],
                -q[0] * w[0] - q[1] * w[1] - q[2] * w[2])

    q = quat_mult_point(rotation, vector)
    q = tf.transformations.quaternion_multiply(q, tf.transformations.quaternion_inverse(rotation))
    return [q[0], q[1], q[2]]

def multiply_transform(t1, t2):
    """
    Combines two transformations together
    The order is translation first, rotation then
    :param t1: [[x, y, z], [x, y, z, w]] or matrix 4x4
    :param t2: [[x, y, z], [x, y, z, w]] or matrix 4x4
    :return: The combination t1-t2 in the form [[x, y, z], [x, y, z, w]] or matrix 4x4
    """
    return [list(quat_rotate(t1[1], t2[0]) + array(t1[0])),
            list(tf.transformations.quaternion_multiply(t1[1], t2[1]))]

# Some conversion functions dealing with formats [[x, y, z], [x, y, z, w]] and [x, y, z, x, y, z, w]
list_to_pose2 = lambda x: list_to_pose(x[0] + x[1])
pose_to_list2 = lambda x: [pose_to_list(x.pose)[:3], pose_to_list(x.pose)[3:]]
list_to_pose_stamped2 = lambda x: list_to_pose_stamped(x[0] + x[1], "base")