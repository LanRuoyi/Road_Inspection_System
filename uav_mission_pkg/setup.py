from setuptools import setup

package_name = "uav_mission_pkg"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/uav_mission_system.launch.py"]),
    ],
    install_requires=["setuptools", "pymavlink", "requests"],
    zip_safe=True,
    maintainer="road-inspection",
    maintainer_email="noreply@example.com",
    description="Integrated MAVLink bridge, capture and upload package.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "mavlink_bridge_node = uav_mission_pkg.mavlink_bridge_node:main",
            "capture_node = uav_mission_pkg.capture_node:main",
            "uploader_node = uav_mission_pkg.uploader_node:main",
        ],
    },
)
