"""
Tornado handler for the 3D page
"""
from __future__ import print_function
import datetime
import os
import sys
import tornado.web
import numpy as np

# this is needed for the following imports
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../plot_app'))
from config import get_bing_maps_api_key, get_cesium_api_key
from helper import validate_log_id, get_log_filename, load_ulog_file, \
    get_flight_mode_changes, flight_modes_table

#pylint: disable=relative-beyond-top-level
from .common import get_jinja_env, CustomHTTPError, TornadoRequestHandlerBase

THREED_TEMPLATE = '3d.html'

#pylint: disable=abstract-method, unused-argument

class ThreeDHandler(TornadoRequestHandlerBase):
    """ Tornado Request Handler to render the 3D Cesium.js page """

    def get(self, *args, **kwargs):
        """ GET request callback """

        # load the log file
        log_id = self.get_argument('log')
        if not validate_log_id(log_id):
            raise tornado.web.HTTPError(400, 'Invalid Parameter')
        log_file_name = get_log_filename(log_id)
        ulog = load_ulog_file(log_file_name)

        # extract the necessary information from the log

        try:
            # required topics: none of these are optional
            gps_pos = ulog.get_dataset('vehicle_gps_position').data
            vehicle_global_position = ulog.get_dataset('vehicle_global_position').data
            attitude = ulog.get_dataset('vehicle_attitude').data
        except (KeyError, IndexError, ValueError) as error:
            raise CustomHTTPError(
                400,
                'The log does not contain all required topics<br />'
                '(vehicle_gps_position, vehicle_global_position, '
                'vehicle_attitude)')

        # These are optional data streams. Most of them are added
        # for charting/streaming 2D plots on the 3D viewer.
        manual_control_setpoint = None
        vehicle_local_position = None
        vehicle_local_position_setpoint = None
        vehicle_attitude_setpoint = None
        vehicle_rates_setpoint = None
        actuator_outputs = None
        sensor_combined = None
        actuator_controls_0 = None

        # Exception handling is done on each dataset separately to find
        # source of the missing stream.

        # Exception: manual_control_setpoint
        try:
            manual_control_setpoint = ulog.get_dataset('manual_control_setpoint').data
        except (KeyError, IndexError, ValueError) as error:
            print("Manual control setpoint not found")

        # Exception: vehicle_local_position
        try:
            vehicle_local_position = ulog.get_dataset('vehicle_local_position').data
        except (KeyError, IndexError, ValueError) as error:
            print("Vehicle local position not found")

        # Exception: vehicle_local_position_setpoint
        try:
            vehicle_local_position_setpoint = ulog.get_dataset('vehicle_local_position_setpoint').data
        except (KeyError, IndexError, ValueError) as error:
            print("Vehicle local position setpoint not found")   

        # Exception: vehicle_attitude_setpoint
        try:
            vehicle_attitude_setpoint = ulog.get_dataset('vehicle_attitude_setpoint').data
        except (KeyError, IndexError, ValueError) as error:
            print("Vehicle attitude setpoint not found")                       

        # Exception: vehicle_rates_setpoint
        try:
            vehicle_rates_setpoint = ulog.get_dataset('vehicle_rates_setpoint').data
        except (KeyError, IndexError, ValueError) as error:
            print("Vehicle rates setpoint not found")  

        # Exception: actuator_outputs
        try:
            actuator_outputs = ulog.get_dataset('actuator_outputs').data
        except (KeyError, IndexError, ValueError) as error:
            print("Actuator output not found")                  

        # Exception: sensor_combined
        try:
            sensor_combined = ulog.get_dataset('sensor_combined').data
        except (KeyError, IndexError, ValueError) as error:
            print("Sensor combined not found")      

        # Exception: actuator_controls_0
        try:
            actuator_controls_0 = ulog.get_dataset('actuator_controls_0').data
        except (KeyError, IndexError, ValueError) as error:
            print("Actuator Controls 0 not found")   

        # Get the takeoff location. We use the first position with a valid fix,
        # and assume that the vehicle is not in the air already at that point
        takeoff_index = 0
        gps_indices = np.nonzero(gps_pos['fix_type'] > 2)
        if len(gps_indices[0]) > 0:
            takeoff_index = gps_indices[0][0]
        takeoff_altitude = '{:.3f}' \
            .format(gps_pos['alt'][takeoff_index] * 1.e-3)
        takeoff_latitude = '{:.10f}'.format(gps_pos['lat'][takeoff_index] * 1.e-7)
        takeoff_longitude = '{:.10f}'.format(gps_pos['lon'][takeoff_index] * 1.e-7)


        # calculate UTC time offset (assume there's no drift over the entire log)
        utc_offset = int(gps_pos['time_utc_usec'][takeoff_index]) - \
                int(gps_pos['timestamp'][takeoff_index])

        # flight modes
        flight_mode_changes = get_flight_mode_changes(ulog)
        flight_modes_str = '[ '
        for t, mode in flight_mode_changes:
            t += utc_offset
            utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                tzinfo=datetime.timezone.utc)
            if mode in flight_modes_table:
                mode_name, color = flight_modes_table[mode]
            else:
                mode_name = ''
                color = '#ffffff'
            flight_modes_str += '["{:}", "{:}"], ' \
                .format(utctimestamp.isoformat(), mode_name)
        flight_modes_str += ' ]'

        # manual control setpoints (stick input)
        manual_control_setpoints_str = '[ '
        if manual_control_setpoint:
            for i in range(len(manual_control_setpoint['timestamp'])):
                manual_x = manual_control_setpoint['x'][i]
                manual_y = manual_control_setpoint['y'][i]
                manual_z = manual_control_setpoint['z'][i]
                manual_r = manual_control_setpoint['r'][i]
                t = manual_control_setpoint['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                manual_control_setpoints_str += '["{:}", {:.3f}, {:.3f}, {:.3f}, {:.3f}], ' \
                    .format(utctimestamp.isoformat(), manual_x, manual_y, manual_z, manual_r)
        manual_control_setpoints_str += ' ]'


        # position
        # Note: alt_ellipsoid from gps_pos would be the better match for
        # altitude, but it's not always available. And since we add an offset
        # (to match the takeoff location with the ground altitude) it does not
        # matter as much.
        position_data = '[ '
        # TODO: use vehicle_global_position? If so, then:
        # - altitude requires an offset (to match the GPS data)
        # - it's worse for some logs where the estimation is bad -> acro flights
        #   (-> add both: user-selectable between GPS & estimated trajectory?)
        for i in range(len(gps_pos['timestamp'])):
            lon = gps_pos['lon'][i] * 1.e-7
            lat = gps_pos['lat'][i] * 1.e-7
            alt = gps_pos['alt'][i] * 1.e-3
            t = gps_pos['timestamp'][i] + utc_offset
            utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                tzinfo=datetime.timezone.utc)
            if i == 0:
                start_timestamp = utctimestamp
            end_timestamp = utctimestamp
            position_data += '["{:}", {:.10f}, {:.10f}, {:.3f}], ' \
                .format(utctimestamp.isoformat(), lon, lat, alt)
        position_data += ' ]'

        start_timestamp_str = '"{:}"'.format(start_timestamp.isoformat())
        boot_timestamp = datetime.datetime.utcfromtimestamp(utc_offset/1.e6).replace(
            tzinfo=datetime.timezone.utc)
        boot_timestamp_str = '"{:}"'.format(boot_timestamp.isoformat())
        end_timestamp_str = '"{:}"'.format(end_timestamp.isoformat())

        # orientation as quaternion
        attitude_data = '[ '
        for i in range(len(attitude['timestamp'])):
            att_qw = attitude['q[0]'][i]
            att_qx = attitude['q[1]'][i]
            att_qy = attitude['q[2]'][i]
            att_qz = attitude['q[3]'][i]
            rollSpeed = attitude['rollspeed'][i]
            pitchSpeed = attitude['pitchspeed'][i]
            yawSpeed = attitude['yawspeed'][i]
            t = attitude['timestamp'][i] + utc_offset
            utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                tzinfo=datetime.timezone.utc)
            # Cesium uses (x, y, z, w)
            attitude_data += '["{:}", {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}], ' \
                .format(utctimestamp.isoformat(), att_qx, att_qy, att_qz, att_qw, rollSpeed, pitchSpeed, yawSpeed)
        attitude_data += ' ]'

        # Optional data stream serialization starts here.
        # The code checks None condition to decide whether
        # to serialize or not.

        # Attitude setpoint data
        vehicle_rates_setpoint_data = '[ '
        if vehicle_rates_setpoint is not None:
            for i in range(len(vehicle_rates_setpoint['timestamp'])):
                rollRateSP = vehicle_rates_setpoint['roll'][i]
                pitchRateSP = vehicle_rates_setpoint['pitch'][i]
                yawRateSp = vehicle_rates_setpoint['yaw'][i]
                t = vehicle_rates_setpoint['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                vehicle_rates_setpoint_data += '["{:}", {:.6f}, {:.6f}, {:.6f}], ' \
                    .format(utctimestamp.isoformat(), rollRateSP, pitchRateSP, yawRateSp)
        vehicle_rates_setpoint_data += ' ]'        

        # Sensor combined data. Includes things like raw gyro, raw accelleration.
        sensor_combined_data = '[ '
        if sensor_combined is not None:
            for i in range(len(sensor_combined['timestamp'])):
                rawRoll = sensor_combined['gyro_rad[0]'][i]
                rawPitch = sensor_combined['gyro_rad[1]'][i]
                rawYaw = sensor_combined['gyro_rad[2]'][i]
                rawXAcc = sensor_combined['accelerometer_m_s2[0]'][i]
                rawYAcc = sensor_combined['accelerometer_m_s2[1]'][i]
                rawZAcc = sensor_combined['accelerometer_m_s2[2]'][i]            
                t = sensor_combined['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                sensor_combined_data += '["{:}", {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}], ' \
                    .format(utctimestamp.isoformat(), rawRoll, rawPitch, rawYaw, rawXAcc, rawYAcc, rawZAcc)
        sensor_combined_data += ' ]'         

        # Attitude setpoint
        vehicle_attitude_setpoint_data = '[ '
        if vehicle_attitude_setpoint is not None:
            for i in range(len(vehicle_attitude_setpoint['timestamp'])):
                rollSP = vehicle_attitude_setpoint['roll_body'][i]
                pitchSP = vehicle_attitude_setpoint['pitch_body'][i]
                yawSP = vehicle_attitude_setpoint['yaw_body'][i]

                t = vehicle_attitude_setpoint['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                vehicle_attitude_setpoint_data += '["{:}", {:.6f}, {:.6f}, {:.6f}], ' \
                    .format(utctimestamp.isoformat(), rollSP, pitchSP, yawSP)
        vehicle_attitude_setpoint_data += ' ]'    

        # Local Position
        vehicle_local_position_data = '[ '
        if vehicle_local_position is not None:
            for i in range(len(vehicle_local_position['timestamp'])):
                xPos = vehicle_local_position['x'][i]
                yPos = vehicle_local_position['y'][i]
                zPos = vehicle_local_position['z'][i]
                xVel = vehicle_local_position['vx'][i]
                yVel = vehicle_local_position['vy'][i]
                zVel = vehicle_local_position['vz'][i]            

                t = vehicle_local_position['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                vehicle_local_position_data += '["{:}", {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}], ' \
                    .format(utctimestamp.isoformat(), xPos, yPos, zPos, xVel, yVel, zVel)
        vehicle_local_position_data += ' ]'   

        # Local Position Setpoint
        vehicle_local_position_setpoint_data = '[ '
        if vehicle_local_position_setpoint is not None:
            for i in range(len(vehicle_local_position_setpoint['timestamp'])):
                xPosSP = vehicle_local_position_setpoint['x'][i]
                yPosSP = vehicle_local_position_setpoint['y'][i]
                zPosSP = vehicle_local_position_setpoint['z'][i]
                xVelSP = vehicle_local_position_setpoint['vx'][i]
                yVelSP = vehicle_local_position_setpoint['vy'][i]
                zVelSP = vehicle_local_position_setpoint['vz'][i]

                t = vehicle_local_position_setpoint['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                vehicle_local_position_setpoint_data += '["{:}", {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}, {:.6f}], ' \
                    .format(utctimestamp.isoformat(), xPosSP, yPosSP, zPosSP, xVelSP, yVelSP, zVelSP)
        vehicle_local_position_setpoint_data += ' ]'       

        # Actuator Outputs. This can handle airframes up to 8 actuation outputs (i.e. motors).
        # Tons of formatting things ...

        actuator_outputs_data = '[ '
        if actuator_outputs is not None:
            num_actuator_outputs = 8
            max_outputs = np.amax(actuator_outputs['noutputs'])
            if max_outputs < num_actuator_outputs: num_actuator_outputs = max_outputs

            
            for i in range(len(actuator_outputs['timestamp'])):

                t = actuator_outputs['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)            

                actuatorList = []
                actuatorList.append(utctimestamp.isoformat())
                actuatorDictionary={}
                formatStringLoop = ''
                for x in range(max_outputs):
                    actuatorDictionary["actuator_outputs_{0}".format(x)]=actuator_outputs['output['+str(x)+']'][i]
                    formatStringLoop += ', {:.6f}'
                    actuatorList.append(actuatorDictionary["actuator_outputs_{0}".format(x)])
                formatStringLoop += '], '   
                formatString = '["{:}"' + formatStringLoop

                actuator_outputs_data += formatString.format(*actuatorList)
        actuator_outputs_data += ' ]'          

        # Actuator controls
        actuator_controls_0_data = '[ '
        if actuator_controls_0 is not None:
            for i in range(len(actuator_controls_0['timestamp'])):
                cont0 = actuator_controls_0['control[0]'][i]
                cont1 = actuator_controls_0['control[1]'][i]
                cont2 = actuator_controls_0['control[2]'][i]
                cont3 = actuator_controls_0['control[3]'][i]

                t = actuator_controls_0['timestamp'][i] + utc_offset
                utctimestamp = datetime.datetime.utcfromtimestamp(t/1.e6).replace(
                    tzinfo=datetime.timezone.utc)
                actuator_controls_0_data += '["{:}", {:.6f}, {:.6f}, {:.6f}, {:.6f}], ' \
                    .format(utctimestamp.isoformat(), cont0, cont1, cont2, cont3)
        actuator_controls_0_data += ' ]'     

        # handle different vehicle types
        # the model_scale_factor should scale the different models to make them
        # equal in size (in proportion)
        mav_type = ulog.initial_parameters.get('MAV_TYPE', None)
        if mav_type == 1: # fixed wing
            model_scale_factor = 0.06
            model_uri = 'plot_app/static/cesium/SampleData/models/CesiumAir/Cesium_Air.glb'
        elif mav_type == 2: # quad
            model_scale_factor = 1
            model_uri = 'plot_app/static/cesium/models/iris/iris.glb'
        elif mav_type == 22: # delta-quad
            # TODO: use the delta-quad model
            model_scale_factor = 0.06
            model_uri = 'plot_app/static/cesium/SampleData/models/CesiumAir/Cesium_Air.glb'
        else: # TODO: handle more types
            model_scale_factor = 1
            model_uri = 'plot_app/static/cesium/models/iris/iris.glb'

        template = get_jinja_env().get_template(THREED_TEMPLATE)
        self.write(template.render(
            flight_modes=flight_modes_str,
            manual_control_setpoints=manual_control_setpoints_str,
            takeoff_altitude=takeoff_altitude,
            takeoff_longitude=takeoff_longitude,
            takeoff_latitude=takeoff_latitude,
            position_data=position_data,
            start_timestamp=start_timestamp_str,
            boot_timestamp=boot_timestamp_str,
            end_timestamp=end_timestamp_str,
            attitude_data=attitude_data,
            vehicle_attitude_setpoint_data = vehicle_attitude_setpoint_data,
            vehicle_local_position_data = vehicle_local_position_data,
            vehicle_local_position_setpoint_data = vehicle_local_position_setpoint_data,
            actuator_outputs_data = actuator_outputs_data,
            vehicle_rates_setpoint_data = vehicle_rates_setpoint_data,
            sensor_combined_data = sensor_combined_data,
            actuator_controls_0_data = actuator_controls_0_data,
            model_scale_factor=model_scale_factor,
            model_uri=model_uri,
            log_id=log_id,
            bing_api_key=get_bing_maps_api_key(),
            cesium_api_key=get_cesium_api_key()))

