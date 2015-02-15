"""
.. module:: zeroMQInterface
    :synopsis: Wraps ZeroMQ library with a simplified publish/subscribe
    interface.  The serialize data protocol is MessagePack.  The python 
    dictionary is used as a standardized format.  The subscribe gets the 
    contents of messages, but also the publisher address and the topic.
"""
import os
import sys
scriptDir=os.path.dirname(os.path.realpath(__file__))
sys.path.append(scriptDir)
import zmq
import json
import msgpack
import importlib
import pdb
import utils
import logMessageAdapter
PUB_BUFF_SIZE = 100000

# static functions
def _extractProcessConfig(processList, processName):
    """
    Tries to find specific process dictionary settings at supplied
    process path.
    :param processList: list of processes dictionaries
    :type processList: list 
    :return: dictionary of process settings
    :raises: ValueError
    """
    processDict = {}
    for process in processList:
        if ('processName' in process and process['processName'] == processName):
            processDict = process
            break
    
    if (not(processDict)):
        raise ValueError("Process configuration not found in config file")

    return processDict

def _extractConfig(configFilePath, publisherName):

    processList = utils.separatePathAndModule(configFilePath)
    processConfigDict = _extractProcessConfig(processList, publisherName)

    if ('endPoint' in processConfigDict):
        endPointAddress = processConfigDict['endPoint']
        print (publisherName + ' binding to address ' + str(endPointAddress))
    else:
        raise ValueError("'endPoint' missing from process config")

    return endPointAddress, processConfigDict

class ZeroMQPublisher():
    def __init__(self, endPointAddress=None):
        """
        Constructor.  Sets up ZeroMQ publisher socket.

        :param number port: integer designating the port number of the publisher
        """
        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.set_hwm(PUB_BUFF_SIZE)
        if (endPointAddress is not(None)):
            self.bind(endPointAddress)

    def __del__(self):
        """
        Destructor.  Closes sockets
        """
        self.publisher.close()
        self.context.term()

    def bind(self, endPointAddress):
        self.endPointAddress = endPointAddress
        self.publisher.bind(endPointAddress)

    def importProcessConfig(self, configFilePath, 
        publisherName=utils.getModuleName(os.path.realpath(__file__))):
        """
        Registers publisher settings based off config file
        :param configFilePath: full config file path
        :type configFilePath: str
        :param publisherPath: path to publisher process file (defaults to current file)
        :type publisherPath: str
        :raises: ValueError    
        """
        self.endPointAddress, self.processConfigDict = _extractConfig(configFilePath, 
            publisherName)
        self.bind(self.endPointAddress)
        #self.processList = utils.separatePathAndModule(configFilePath)
        #self.processConfigDict = _extractProcessConfig(self.processList, publisherName)

        #if ('endPoint' in self.processConfigDict):
        #    self.endPointAddress = self.processConfigDict['endPoint']
        #    self.publisher.bind(self.endPointAddress)
        #    print (publisherName + ' binding to address ' + str(self.endPointAddress))
        #else:
        #    raise ValueError("'endPoint' missing from process config")

    def send(self, topic, dict):
        """
        Main send function over ZeroMQ socket.  Input dictionary gets
        serialized and sent over wire.

        :param str topic: string representing the message topic
        :param dictionary dict: data payload input
        """

        serialDict = msgpack.dumps(dict)
        self.publisher.send_multipart([str.encode(topic),str.encode(self.endPointAddress),
            serialDict])


class ZeroMQSubscriber():
    def __init__(self, publisherRef=None):
        """
        Constructor.  Sets up ZeroMQ subscriber socket and poller object
        :return:
        """
        self.context = zmq.Context()
        self.subscriberList = []
        self.poller = zmq.Poller()
        if (publisherRef is not(None)):
            self.logPublisher = publisherRef

    def __del__(self):
        """
        Destructor.  Closes ZeroMQ connections.
        """
        for item in self.subscriberList:
            item.close()

        self.context.term()

    def setPublisherRef(self, publisherRef):
        self.logPublisher = publisherRef

    def importProcessConfig(self, configFilePath, subscriberName=utils.getModuleName(os.path.realpath(__file__))):
        """
        Registers subscriber settings based off config file
        :param configFilePath: full config file path
        :type configFilePath: str
        :param subscriberPath: path to subscriber process file (defaults to current file)
        :type subscriberPath: str
        :raises: ValueError    
        """
        #self.processList = utils.separatePathAndModule(configFilePath)
        #self.processConfigDict = _extractProcessConfig(self.processList, subscriberName)
        
        #if ('endPoint' in self.processConfigDict):
        #    self.endPoint = self.processConfigDict['endPoint']
        #else:
        #    raise ValueError('No endpoint provided in process config')

        self.endPointAddress, self.processConfigDict = _extractConfig(configFilePath, 
            subscriberName)

        self.logAdapter = logMessageAdapter.LogMessageAdapter(subscriberName)

        if ('subscriptions' in self.processConfigDict):
            for subDict in self.processConfigDict['subscriptions']:
                if ('endPoint' in subDict):
                    self.connectSubscriber(subDict['endPoint'])
                    #print ('connecting ' + subscriberName + ' to ' + str(subDict['endPoint']))
                    logMsg = 'connecting ' + subscriberName + ' to ' + str(subDict['endPoint'])
                    self.logPublisher.send('log', self.logAdapter.genLogMessage(logLevel=1, message=logMsg))
                    if ('topics' in subDict):
                        for topic in subDict['topics']:
                            self.subscribeToTopic(topic)
                            print('subscribing to topic ' + str(topic))
                    else:
                        print('Warning: No topics found for subscribed endpoint: ' + str(subDict['endPoint']))
                else:
                    raise ValueError("No endpoint specified in process config")

    def connectSubscriber(self, endPointAddress):
        """
        Method to create subscriber connection to a particular publisher
        :param number port: integer representing the port number of the publisher to connect to
        :param str topic: string that is used to filter unwanted messages from publisher
        """
        self.subscriberList.append(self.context.socket(zmq.SUB))
        self.subscriberList[-1].connect(endPointAddress)
        self.poller.register(self.subscriberList[-1], zmq.POLLIN)

    def subscribeToTopic(self, topic):
        """
        Subscribes class instance to most recently connected subscriber
        :param topic: topic to subscriber to (filters other topics if not subscribed)
        :type topic: str
        """
        self.subscriberList[-1].setsockopt(zmq.SUBSCRIBE, str.encode(topic))

    def _byteToString(self, inBytes):
        if (type(inBytes)==bytes):
            return inBytes.decode()
        else:
            return inBytes

    def _convert_keys_to_string(self, inDict):
        """
        Converts byte encoded keys to string.  Need this because msgpack unpack 
        doesn't decode all the elements in the serialized data stream
        :param dictionary inDict: any non-nested key value dictionary
        :return: dictionary 
        """
        newDict = {}
        for key, value in inDict.items():
            if (type(value) == dict):
                # this might blow up, need to test more
                value = self._convert_keys_to_string(value)

            newDict[self._byteToString(key)] = self._byteToString(value)  

        return newDict

    def receive(self):
        """
        Method that polls all available connections and returns a dictionary.  This should
        get called continuously to continue receiving messages.  Currently, this function
        will not block if no messages are available.  
        :return: list of nested dictionaries
        """
        socks = []
        try:
            socks = dict(self.poller.poll(0.1))
        except:
            print ('exception occurred on subscribed receive function')

        responseList = []
        if (len(socks)>0):
            for listItem in self.subscriberList:
                if listItem in socks:
                    topic, pubAddress, contents = listItem.recv_multipart()

                    convertedContents = self._convert_keys_to_string(msgpack.loads(contents)) 
                    responseList.append({
                        'topic': topic.decode(), 
                        'pubAddress': pubAddress.decode(), 
                        'contents': convertedContents
                    })                   

        return responseList