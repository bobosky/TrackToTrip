import gpxpy
from os.path import basename
from .segment import Segment
from copy import deepcopy
from similarity import segment_similarity
from rtree import index
import numpy as np
import defaults

DEFAULT_FILE_NAME_FORMAT = "%Y-%m-%d"

class Track:
    """Collection of segments

    This is a higher level class, all methods of TrackToTrip library
    can be called over this class

    Attributes:
        name: A string indicating the name of the track
        segments: Array of TrackToTrip Segments
        preprocessed: Boolean, true if it has been preprocessed
    """

    def __init__(self, name="", segments=[]):
        """Constructor

        When constructing a track it's not guaranteed that the segments
        have their properties computed. Call preprocess method over this
        class, or over each segment to guarantee it.

        Args:
            name: optional, name of the current track. The default value
                is a empty string
            segments: optional, array of TrackToTripSegments. The default
                value is an empty array
        """
        self.name = name
        self.segments = sorted(segments, key=lambda s: s.getStartTime())
        self.preprocessed = False

    def segmentAt(self, i):
        """Segment at index

        Args:
            i: index of segment to return
        Returns:
            A TrackToTrip segment or an excption for index out of range
        """
        return self.segments[i]

    def getStartTime(self):
        lastTime = None
        for segment in self.segments:
            if lastTime is None:
                lastTime = segment.getStartTime()
            elif lastTime > segment.getStartTime():
                lastTime = segment.getStartTime()
        return lastTime

    def generateName(self, f=DEFAULT_FILE_NAME_FORMAT):
        """Generates a name for the track

        The name is generated based on the date of the first point of the
        track, or in case it doesn't exist, "EmptyTrack"
        The DEFAULT_FILE_NAME_FORMAT constant constains the date format

        Returns:
            A string of the generated name
        """
        if len(self.segments) > 0:
            return self.segmentAt(0).pointAt(0).time.strftime(f) + ".gpx"
        else:
            return "EmptyTrack"

    def removeNoise(self, var=2):
        """In-place removal of noise points

        Arguments:
            var: Number to adjust noise removal sensitivity
        Returns:
            This track
        """
        for segment in self.segments:
            segment.removeNoise(var)
        return self

    def smooth(self, strategy=defaults.SMOOTH_STRATEGY, noise=defaults.SMOOTH_NOISE):
        """In-place smoothing of segments

        Returns:
            This track
        """
        for segment in self.segments:
            segment.smooth(strategy=strategy, noise=noise)
        return self

    def segment(self, eps=defaults.SEGMENT_EPS, min_time=defaults.SEGMENT_MIN_TIME):
        """In-place segmentation of segments

        Spatio-temporal segmentation of each segment
        The number of segments may increse after this step

        Returns:
            This track
        """
        newSegments = []
        for segment in self.segments:
            s = segment.segment(eps=eps, min_time=min_time)
            for a in s:
                newSegments.append(Segment(a))
        self.segments = newSegments
        return self

    def simplify(self, topology_only=False, dist_threshold=defaults.SIMPLIFY_DISTANCE_THRESHOLD):
        """In-place simplification of segments

        Args:
            topology_only: Boolean, optional. True to keep
                the topology, neglecting velocity and time
                accuracy (use common Douglas-Ramen-Peucker).
                False (default) to simplify segments keeping
                the velocity between points.
        Returns:
            This track
        """
        for segment in self.segments:
            segment.simplify(topology_only, dist_threshold=dist_threshold)
        return self

    def inferTransportationMode(self, clf, removeStops=defaults.TM_REMOVE_STOPS, dt_threshold=defaults.TM_DT_THRESHOLD):
        """In-place transportation mode inferring of segments

        Returns:
            This track
        """
        for segment in self.segments:
            segment.inferTransportationMode(clf, removeStops=removeStops, dt_threshold=dt_threshold)
        return self

    def copy(self):
        """Creates a deep copy of itself

        All segments and points are copied

        Returns:
            A Track object different from this instance
        """

        return deepcopy(self)

    def toTrip(
        self,
        name="",
        noise_var=2,
        smooth_strategy='inverse',
        smooth_noise=defaults.SMOOTH_NOISE,
        seg_eps=defaults.SEGMENT_EPS,
        seg_min_time=defaults.SEGMENT_MIN_TIME,
        simplify_dist_threshold=defaults.SIMPLIFY_DISTANCE_THRESHOLD,
        simplify_max_time=5,
        file_format=DEFAULT_FILE_NAME_FORMAT
    ):
        """In-place, transformation of a track into a trip

        A trip is a more accurate depiction of reality than a
        track.
        For a track to become a trip it need to go through the
        following steps:
            + noise removal
            + smoothing
            + spatio-temporal segmentation
            + simplification
        At the end of these steps we have a less noisy, track
        that has less points, but that holds the same information.
        It's required that each segment has their metrics calculated
        or has been preprocessed.

        Args:
            name: An optional string with the name of the trip. If
                none is given, one will be generated by generateName
        Returns:
            This Track instance
        """
        if len(name) != 0:
            name = self.name
        else:
            name = self.generateName(file_format)

        # self.removeNoise(noise_var)

        self.smooth(smooth_strategy, smooth_noise)

        self.compute_metrics()
        self.segment(seg_eps, seg_min_time)

        self.compute_metrics()
        self.simplify(dist_threshold=simplify_dist_threshold)

        self.compute_metrics()
        self.name = name

        return self

    def preprocess(self, destructive=True, max_acc=defaults.PREPROCESS_MAX_ACC):
        """In-place preprocessing of segments

        Args:
            destructive: Optional, boolean. True to allow point
                removal. More details in preprocessSegment
        Returns:
            This track
        """
        self.segments = map(lambda segment: segment.preprocess(destructive, max_acc), self.segments)
        self.preprocessed = True
        return self

    def inferTransportationModes(self, removeStops=False, dt_threshold=10):
        """In-place transportation inferring of segments

        Returns:
            This track
        """
        self.segments = map(lambda segment: segment.inferTransportationMode(removeStops=removeStops, dt_threshold=dt_threshold), self.segments)
        return self

    def inferLocation(
        self,
        location_query,
        max_distance=defaults.LOCATION_MAX_DISTANCE,
        google_key='',
        limit=defaults.LOCATIONS_LIMIT
    ):
        """In-place location inferring of segments

        Returns:
            This track
        """
        self.segments = map(lambda segment: segment.inferLocation(
            location_query,
            max_distance,
            google_key,
            limit
        ), self.segments)
        return self

    def toJSON(self):
        """Converts track to a JSON serializable format

        Returns:
            Map with the name, and segments of the track.
        """
        return {
                'name': self.name,
                'segments': map(lambda segment: segment.toJSON(), self.segments)
                }

    def merge_and_fit(self, track, ff, threshold=0):
        for (selfSegIndex, trackSegIndex, diffs) in ff:
            selfS = self.segments[selfSegIndex]
            trackS = track.segments[trackSegIndex]

            selfS.merge_and_fit(trackS)
        return self

    # def trim(self, p1, p2):
        # s1, pi1 = self.getPointIndex(p1)
        # s2, pi2 = self.getPointIndex(p2)

        # if s1 > s2:
            # temp = s1
            # s1 = s2
            # s2 = temp

        # if s2 == s1 and pi1 > pi2:
            # temp = pi1
            # pi1 = pi2
            # pi2 = temp

        # for i, segment in self.segments:
            # if s1 <= i and i <= s2:


        # return

    def getPointIndex(self, point):
        for i, segment in enumerate(self.segments):
            idx = segment.getPointIndex(point)
            if idx != -1:
                return i, idx
        return -1, -1

    def getBounds(self):
        minLat = float("inf")
        minLon = float("inf")
        maxLat = -float("inf")
        maxLon = -float("inf")
        for segment in self.segments:
            milat, milon, malat, malon = segment.getBounds()
            minLat = min(milat, minLat)
            minLon = min(milon, minLon)
            maxLat = max(malat, maxLat)
            maxLon = max(malon, maxLon)
        return minLat, minLon, maxLat, maxLon

    def hasPoint(self, point):
        s_ix, _ = self.getPointIndex(point)
        return s_ix != -1

    def similarity(self, track):
        """Compares two tracks based on their topology

        This method compares the given track against this
        instance. It only verifies if given track is close
        to this one, not the other way arround

        Args:
            track: tracktotrip.Track to be compared with
        Returns:
            Two-tuple with global similarity between tracks
            and an array the similarity between segments
        """

        idx = index.Index()
        n = 0
        for segment in self.segments:
            idx.insert(n, segment.getBounds(), obj=segment)
            n = n + 1

        final_siml = []
        final_diff = []
        for i, segment in enumerate(track.segments):
            query = idx.intersection(segment.getBounds(), objects=True)

            res_siml = []
            res_diff = []
            for result in query:
                siml, diff = segment_similarity(segment, result.object)
                res_siml.append(siml)
                res_diff.append((result.id, i, diff))
                # print(result.id, i, diff)

            # print("seg match", res_siml, res_diff)

            if len(res_siml) > 0:
                final_siml.append(max(res_siml))
                final_diff.append(res_diff[np.argmax(res_siml)])
            else:
                final_siml.append(0)
                final_diff.append([])

        # print("fin", final_siml, final_diff)
        return np.mean(final_siml), final_diff

    def compute_metrics(self):
        for segment in self.segments:
            segment.compute_metrics()
        return self

    def toGPX(self):
        """Converts track to a GPX format

        Uses GPXPY library as an intermediate format

        Returns:
            A string with the GPX/XML track
        """
        gpx = gpxpy.gpx.GPX()
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx.tracks.append(gpx_track)

        for segment in self.segments:
            gpx_segment = gpxpy.gpx.GPXTrackSegment()
            gpx_track.segments.append(gpx_segment)

            for point in segment.points:
                gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(point.lat, point.lon, time=point.time))
        return gpx.to_xml()

    def toLIFE(self):
        """Converts track to LIFE format
        """
        buff = "--%s\n" % self.segments[0].points[0].time.strftime("%Y_%m_%d")
        # buff += "--" + day
        # buff += "UTC+s" # if needed

        def militaryTime(time):
            return time.strftime("%H%M")

        def stay(buff, start, end, place):
            if type(start) is not str:
                start = militaryTime(start)
            if type(end) is not str:
                end = militaryTime(end)

            return "%s\n%s-%s: %s" % (buff, start, end, place.label)

        def trip(buff, segment):
            tp = "%s-%s: %s -> %s" % (
                militaryTime(segment.points[0].time),
                militaryTime(segment.points[-1].time),
                segment.location_from.label,
                segment.location_to.label
            )

            t_modes = segment.transportation_modes
            if len(t_modes) == 1:
                tp = "%s [%s]" % (tp, t_modes[0]['label'])
            else:
                modes = []
                for mode in t_modes:
                    f = militaryTime(segment.points[mode['from']].time)
                    t = militaryTime(segment.points[mode['to']].time)
                    modes.append("    %s-%s: [%s]" % (f, t, mode['label']))
                tp = "%s\n%s" % (tp, "\n".join(modes))

            return "%s\n%s" % (buff, tp)

        LAST = len(self.segments) - 1
        for i, segment in enumerate(self.segments):
            if i == 0:
                buff = stay(buff, "0000", militaryTime(segment.points[0].time), segment.location_from)
            buff = trip(buff, segment)
            if i is LAST:
                buff = stay(buff, militaryTime(segment.points[0].time), "2359", segment.location_to)
            else:
                next_seg = self.segments[i+1]
                buff = stay(buff, militaryTime(segment.points[-1].time), militaryTime(next_seg.points[0].time), segment.location_from)

        return buff

        # TODO use LIFE own types

        # spans = []
        # D_SPAN_FORMAT = "%H%M"
        # for segment in self.segments:
            # span_time = "%s%s" % (segment.getStartTime().strftime(D_SPAN_FORMAT), segment.getEndTime().strftime(D_SPAN_FORMAT))
            # buf = "%s: %s" % (span_time, segment.locationFrom.label)
            # if segment.locationTo != None:
                # buf = "%s "
        return ""

    @staticmethod
    def fromGPX(filePath):
        """Creates a Track from a GPX file.

        No preprocessing is done.

        Arguments:
            filePath: file path and name to the GPX file
        Return:
            A Track instance
        """
        gpx = gpxpy.parse(open(filePath, 'r'))
        fileName = basename(filePath)

        tracks = []
        for ti, track in enumerate(gpx.tracks):
            segments = []
            for segment in track.segments:
                segments.append(Segment.fromGPX(segment))

            if len(gpx.tracks) > 1:
                name = fileName + "_" + str(ti)
            else:
                name = fileName
            tracks.append(Track(name, segments))

        return tracks

    @staticmethod
    def fromJSON(json):
        """Creates a Track from a JSON file.

        No preprocessing is done.

        Arguments:
            json: map with the keys: name (optional) and segments.
        Return:
            A track instance
        """
        segments = map(lambda s: Segment.fromJSON(s), json['segments'])
        return Track(json['name'], segments).preprocess()
