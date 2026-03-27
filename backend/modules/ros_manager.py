import roslibpy
import time
from threading import Lock

class ROSManager:
    def __init__(self):
        self.client = None
        self.topics = {}      # 存储 Topic 对象
        self.data_cache = {}   # 存储最新消息
        self.ref_counts = {}   # 存储每个话题的引用计数 {topic_name: count}
        self._lock = Lock()

    @property
    def is_connected(self):
        return self.client is not None and self.client.is_connected

    def connect(self, host, port):
        if self.is_connected: return True
        try:
            if self.client: self.client.connect()
            else:
                self.client = roslibpy.Ros(host=host, port=port)
                self.client.run()
            timeout = 5
            start = time.time()
            while not self.client.is_connected and (time.time() - start) < timeout:
                time.sleep(0.1)
            return self.client.is_connected
        except:
            self.client = None
            return False

    def subscribe(self, topic_name, topic_type):
        if not self.is_connected or not topic_name: return

        with self._lock:
            # 引用计数增加
            self.ref_counts[topic_name] = self.ref_counts.get(topic_name, 0) + 1
            current_ref_count = self.ref_counts[topic_name]

        # 如果是第一次订阅该话题，或者类型变了，执行物理订阅
        if topic_name not in self.topics:
            try:
                topic = roslibpy.Topic(self.client, topic_name, topic_type)
                topic.subscribe(lambda msg: self._update_cache(topic_name, msg))
                self.topics[topic_name] = topic
            except: pass
        else:
            # 如果话题已存在但类型不符，且当前只有这一个引用，则重置它
            existing_type = getattr(self.topics[topic_name], 'message_type', None)
            if existing_type != topic_type and current_ref_count <= 1:
                self.unsubscribe_topic(topic_name, force=True)
                self.subscribe(topic_name, topic_type)

    def unsubscribe_topic(self, topic_name, force=False):
        """只有引用计数归零时才真正退订"""
        with self._lock:
            if topic_name not in self.ref_counts:
                return

            if not force:
                self.ref_counts[topic_name] -= 1

            should_unsubscribe = self.ref_counts[topic_name] <= 0 or force

        if should_unsubscribe:
            if topic_name in self.topics:
                try:
                    self.topics[topic_name].unsubscribe()
                    self.topics.pop(topic_name)
                    with self._lock:
                        self.data_cache.pop(topic_name, None)
                except: pass
            with self._lock:
                self.ref_counts.pop(topic_name, None)

    def disconnect(self):
        try:
            for t_name in list(self.topics.keys()):
                self.unsubscribe_topic(t_name, force=True)
            if self.client: self.client.close()
        except: pass
        finally:
            self.topics = {}
            self.data_cache = {}
            self.ref_counts = {}

    def _update_cache(self, topic_name, msg):
        with self._lock:
            self.data_cache[topic_name] = msg

    def get_all_topics(self):
        if self.is_connected:
            try:
                result = self.client.get_topics()
                if isinstance(result, dict):
                    return result.get('topics', [])
                if isinstance(result, list):
                    return result
                return []
            except: return []
        return []

    def get_topic_type(self, topic_name):
        if not self.is_connected or not topic_name:
            return None
        try:
            topic_type = self.client.get_topic_type(topic_name)
            if isinstance(topic_type, str):
                return topic_type
            return None
        except:
            return None

    def get_topics_with_types(self):
        topics = self.get_all_topics()
        topic_items = []
        for topic_name in topics:
            topic_type = self.get_topic_type(topic_name)
            topic_items.append({
                'name': topic_name,
                'type': topic_type or 'unknown'
            })
        return topic_items

    def get_topic_types(self):
        items = self.get_topics_with_types()
        unique = sorted({item['type'] for item in items if item.get('type')})
        return unique

    def get_frame(self, topic_name):
        with self._lock:
            return self.data_cache.get(topic_name)