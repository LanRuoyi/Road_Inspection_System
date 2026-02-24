import roslibpy
import time

class ROSManager:
    def __init__(self):
        self.client = None
        self.topics = {}      # 存储 Topic 对象
        self.data_cache = {}   # 存储最新消息
        self.ref_counts = {}   # 存储每个话题的引用计数 {topic_name: count}

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

        # 引用计数增加
        self.ref_counts[topic_name] = self.ref_counts.get(topic_name, 0) + 1

        # 如果是第一次订阅该话题，或者类型变了，执行物理订阅
        if topic_name not in self.topics:
            try:
                topic = roslibpy.Topic(self.client, topic_name, topic_type)
                topic.subscribe(lambda msg: self.data_cache.update({topic_name: msg}))
                self.topics[topic_name] = topic
            except: pass
        else:
            # 如果话题已存在但类型不符，且当前只有这一个引用，则重置它
            existing_type = getattr(self.topics[topic_name], 'message_type', None)
            if existing_type != topic_type and self.ref_counts[topic_name] <= 1:
                self.unsubscribe_topic(topic_name, force=True)
                self.subscribe(topic_name, topic_type)

    def unsubscribe_topic(self, topic_name, force=False):
        """只有引用计数归零时才真正退订"""
        if topic_name in self.ref_counts:
            if not force:
                self.ref_counts[topic_name] -= 1
            
            if self.ref_counts[topic_name] <= 0 or force:
                if topic_name in self.topics:
                    try:
                        self.topics[topic_name].unsubscribe()
                        self.topics.pop(topic_name)
                        self.data_cache.pop(topic_name, None)
                    except: pass
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

    def get_all_topics(self):
        if self.is_connected:
            try: return self.client.get_topics()
            except: return []
        return []

    def get_frame(self, topic_name):
        return self.data_cache.get(topic_name)