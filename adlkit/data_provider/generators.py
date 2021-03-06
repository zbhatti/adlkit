# -*- coding: utf-8 -*-
"""
ADLKit
Copyright ©2017 AnomalousDL, Inc.  All rights reserved.

AnomalousDL, Inc. (ADL) licenses this file to you under the Academic and Research End User License Agreement (the
"License"); you may not use this file except in compliance with the License.  You may obtain a copy of the License at

  http://www.anomalousdl.com/licenses/ACADEMIC-LICENSE.txt

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL ADL BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE, either express
or implied.  See the License for the specific language governing permissions and limitations under the License.
"""

import logging as lg
import time

from .config import GENERATOR_OFFSET
from .workers import Worker

generator_logger = lg.getLogger('data_provider.workers.generators')


class BaseGenerator(Worker):
    def __init__(self,
                 comm_driver,
                 # out_queue,
                 batch_size,
                 shared_memory_pointer,
                 class_index_map,
                 file_index_list,
                 translate_col_to_file_name=False,
                 worker_id=999,
                 max_batches=None,
                 delivery_function=None,
                 watched=False,
                 **kwargs):
        super(BaseGenerator, self).__init__(worker_id + GENERATOR_OFFSET, comm_driver=comm_driver, **kwargs)

        # self.out_queue = out_queue
        self.batch_size = batch_size
        self.class_index_map = class_index_map
        self.file_index_list = file_index_list
        self.shared_memory_pointer = shared_memory_pointer
        self.delivery_function = delivery_function
        self.max_batches = max_batches
        self.watched = watched
        self.translate_col_to_file_name = translate_col_to_file_name
        self.generator_id = self.worker_id - GENERATOR_OFFSET
        # self.last_reader_index = None
        self.last_bucket_index = None

    def debug(self, message):
        if isinstance(message, list):
            message = " ".join(message)
        generator_logger.debug(" genera_id={0} ".format(self.worker_id) + message)

    def info(self, message):
        if isinstance(message, list):
            message = " ".join(message)
        generator_logger.info(" genera_id={0} ".format(self.worker_id, self.batch_count) + message)

    def generate(self):
        self.batch_count = 0
        while not self.should_stop():
                # or (
                # self.max_batches is not None and self.batch_count >= self.max_batches):

            # while True or self.max_batches is not None and self.batch_count >= self.max_batches:
            #     Cleaning up
            if self.last_bucket_index is not None:
                self.debug("attempting to get lock to release buckets")
                if self.watched:
                    with self.shared_memory_pointer[self.last_bucket_index][3].get_lock():
                        # self.debug("setting bucket3 to {}".format(
                        #         self.shared_memory_pointer[self.last_reader_index][self.last_bucket_index][
                        #             3].value + 1))
                        self.shared_memory_pointer[self.last_bucket_index][3].value += 1
                else:
                    with self.shared_memory_pointer[self.last_bucket_index][0].get_lock():
                        self.shared_memory_pointer[self.last_bucket_index][0].value = 0

                self.debug(
                        "successfully got lock and released buckets last_bucket_index={0}".format(
                                self.last_bucket_index))

                self.last_bucket_index = None

            # read_batch = None

            self.debug("attempting to get read_batch from out_queue")
            start_time = time.time()
            # try:
            read_batch = self.comm_driver.read('out', block=False)
            # except Queue.Empty:
            # self.debug("out_queue empty, sleeping")
            # self.sleep()
            # finally:
            if read_batch is not None:
                self.debug(
                        "multi_or_out_queue_get_wait_time={0}".format(time.time() - start_time))
                # self.debug("multi_or_out_queue_get_wait_time={0} queue_size={1}".format(
                # time.time() - start_time, self.out_queue.qsize()))

                try:
                    # reader_id, bucket_index, data_sets, batch_id = read_batch
                    bucket_index, data_sets, batch_id = read_batch
                    self.debug("successfully got a read_batch_id={} from the out_queue".format(batch_id))
                except ValueError:
                    yield None

                if self.watched:
                    with self.shared_memory_pointer[bucket_index][2].get_lock():
                        self.debug("writing ahead bucket_index={}".format(bucket_index))
                        # self.debug("setting bucket2 to {}".format(
                        #         self.shared_memory_pointer[reader_id][bucket_index][2].value + 1))
                        self.shared_memory_pointer[bucket_index][2].value += 1

                payload = self.shared_memory_pointer[bucket_index][1]

                self.last_bucket_index = bucket_index
                # self.last_reader_index = reader_id

                for batch_index in range(0, len(payload[0]), self.batch_size):
                    batch = range(len(payload))
                    for data_set_index, data_set in enumerate(payload):
                        batch[data_set_index] = data_set[batch_index:batch_index + self.batch_size]

                    # generators get caught in this loop so redundant checks are necessary
                    # using that De Morgans law yo
                    if self.should_stop() or (self.max_batches is not None and self.batch_count == self.max_batches):
                        raise StopIteration

                    self.debug("attempting to deliver a batch")
                    yield_wait_time = time.time()

                    if self.translate_col_to_file_name:
                        tmp_list = map(lambda x: [self.file_index_list[int(x[0])], int(x[1])],
                                       batch[self.translate_col_to_file_name])

                        batch[self.translate_col_to_file_name] = tmp_list

                    if self.delivery_function is not None:
                        yield self.delivery_function(batch)
                    else:
                        yield tuple(batch)

                    self.debug(
                            "successfully delivered a batch, continuing from generator yield")
                    self.debug("yield_wait_time={0}".format(time.time() - yield_wait_time))
                    self.batch_count += 1
            else:
                self.debug(" out_queue empty, sleeping")
                self.debug(" batch_count={}/{}".format(self.batch_count, self.max_batches))
                self.sleep()

        self.debug("exiting...")
        self.seppuku()
        raise StopIteration
