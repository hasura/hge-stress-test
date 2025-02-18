#!/usr/bin/env python

# import asyncio
import humanize
import subprocess
import sys
import psutil
import collections
import time
import datetime
import multiprocessing as mp
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.animation as anim
import numpy as np
import toml
import requests

Event = collections.namedtuple("Event", "ts typ data")
Pair = collections.namedtuple("Pair", "x y")


def mk_event(t, data=None):
    e = Event(datetime.datetime.now(), t, data)
    # print(e)
    return e


class StressTest(object):
    def __init__(
        self,
        hge_pid,
        bursts_per_loop_min,
        bursts_per_loop_incr,
        mutations_per_burst_min,
        mutations_per_burst_incr,
        request_delay,
        burst_delay,
        loop_delay,
        loop_count,
        measurement_delay,
        payload_path,
        read_payload_path="payload/read.graphql",
        read_delay=0.1,
        use_read_loop=True,
        wait_for_bursts_to_complete=False,
        constant_burst_gap=True,
        kill_read_delay=90
    ):
        self.manager = mp.Manager()
        self.pending_query_count = mp.Value("i")
        self.enable_ekg = True

        self.q = self.manager.list()
        self.burst_end_q = mp.Queue()
        self.burst_span_q = self.manager.list()
        self.mem_q = self.manager.list()
        self.ekg_q = self.manager.list()
        self.burst_service_time_q = self.manager.list()
        self.query_service_time_q = self.manager.list()
        self.mem_instant_q = self.manager.list()

        self.hge_pid = hge_pid
        self.bursts_per_loop = bursts_per_loop_min[0]
        self.bursts_per_loop_min = bursts_per_loop_min
        self.bursts_per_loop_incr = bursts_per_loop_incr
        self.mutations_per_burst = mutations_per_burst_min[0]
        self.mutations_per_burst_min = mutations_per_burst_min
        self.mutations_per_burst_incr = mutations_per_burst_incr
        self.request_delay = request_delay
        self.burst_delay = burst_delay
        self.loop_delay = loop_delay
        self.loop_count = loop_count
        self.measurement_delay = measurement_delay
        self.wait_for_bursts_to_complete = wait_for_bursts_to_complete
        self.payload_path = payload_path
        self.read_payload_path = read_payload_path
        self.read_delay = read_delay
        self.constant_burst_gap = constant_burst_gap
        self.use_read_loop = use_read_loop
        self.kill_read_delay = kill_read_delay

    def measure_rss(self):
        self.mem_instant_q.append(mk_event("mem_rss_idle", data=self.get_hge_rss()))

    def run_read(self):
        t = time.time()
        self.q.append(mk_event("read_start"))

        def run_script():
            subprocess.run(
                ["./run_read.sh", self.read_payload_path],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )

        p = mp.Process(target=run_script)
        p.start()
        p.join()
        t = time.time() - t
        evt = mk_event("read_fin", data=t)
        self.q.append(evt)

    def run_query(self):
        t = time.time()
        self.q.append(mk_event("query_start"))
        with self.pending_query_count.get_lock():
            self.pending_query_count.value += 1

        def run_script():
            subprocess.run(
                ["./run_query.sh", self.payload_path],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )

        p = mp.Process(target=run_script)
        p.start()
        p.join()
        with self.pending_query_count.get_lock():
            self.pending_query_count.value -= 1
        t = time.time() - t
        evt = mk_event("query_fin", data=t)
        self.q.append(evt)
        self.query_service_time_q.append(evt)

    def run_burst(self):
        print(f"r/b: {self.mutations_per_burst}, b/l: {self.bursts_per_loop}")
        t = time.time()
        burst_start = datetime.datetime.now()
        self.q.append(mk_event("burst_start"))
        procs = []
        for i in range(self.mutations_per_burst):
            p = mp.Process(target=self.run_query)
            procs.append(p)
            p.start()
            time.sleep(self.request_delay)
        burst_end = datetime.datetime.now()
        self.q.append(mk_event("burst_end"))
        self.burst_end_q.put("burst_end")
        self.burst_span_q.append((burst_start, burst_end))
        for p in procs:
            p.join()
        t = time.time() - t
        self.q.append(mk_event("burst_fin", data=t))
        self.burst_service_time_q.append(mk_event("burst_fin", data=t))

    def run_read_loop(self):
        print("running read loop")
        count = 0
        time_taken = datetime.timedelta()
        while True:
            t = datetime.datetime.now()
            p = mp.Process(target=self.run_read)
            p.start()
            time.sleep(self.read_delay)
            t = datetime.datetime.now() - t
            time_taken += t
            count += 1
            if count % 100 == 0:
                print(f"{count} reads run in {time_taken} time")
                time_taken = datetime.timedelta()

    def run_loop(self):
        print("running loop")
        self.q.append(mk_event("loop_start"))
        procs = []
        for i in range(self.bursts_per_loop):
            p = mp.Process(target=self.run_burst)
            procs.append(p)
            p.start()
            self.mutations_per_burst += self.mutations_per_burst_incr
            # wait until the burst ends
            if self.constant_burst_gap:
                self.burst_end_q.get()
            time.sleep(self.burst_delay)
            if self.wait_for_bursts_to_complete:
                p.join()
        self.q.append(mk_event("loop_end"))
        # self.measure_rss()
        if not self.wait_for_bursts_to_complete:
            for p in procs:
                p.join()
        self.q.append(mk_event("loop_fin"))

    def run_test(self):
        if self.use_read_loop:
            p = mp.Process(target=self.run_read_loop)
            p.start()
        for i in range(self.loop_count):
            print("running loop")
            self.mutations_per_burst = self.mutations_per_burst_min[i]
            self.bursts_per_loop = self.bursts_per_loop_min[i]
            self.run_loop()
            print("waiting before running loop")
            self.bursts_per_loop += self.bursts_per_loop_incr
            self.measure_rss()
            time.sleep(self.loop_delay)
            self.measure_rss()
        if self.use_read_loop:
            print("waiting before killing read loop")
            time.sleep(self.kill_read_delay)
            print("killing read loop")
            p.terminate()
    
    def get_hge_rss(self):
        hge = psutil.Process(pid=self.hge_pid)
        return hge.memory_info().rss

    def run(self):
        p = mp.Process(target=self.run_test)
        p.start()

        while True:
            # TODO account for delay in measurement itself
            self.mem_q.append(mk_event("mem_rss", data=self.get_hge_rss()))
            if self.enable_ekg:
                ekg = requests.get("http://localhost:9080/dev/ekg").json()
                self.ekg_q.append(mk_event("ekg", data=ekg))
            time.sleep(self.measurement_delay)

        p.join()

    def visualise(self):
        figure, mem_ax = plt.subplots()
        figure.suptitle(
            f"{self.mutations_per_burst_min}(+{self.mutations_per_burst_incr}) reqs + "
            + f"{self.request_delay}s > "
            + f"{self.bursts_per_loop_min}(+{self.bursts_per_loop_incr}) bursts + "
            + f"{self.burst_delay}s > "
            + f"{self.loop_count} loops + {self.loop_delay}s"
        )
        # time_ax = mem_ax.twinx()
        giga = 10 ** 9
        mem_ax.set_ylim([0, 24 * giga])
        mem_ax.yaxis.set_ticks(np.arange(0, 24 * giga, giga))
        # mem_ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(5))
        mem_ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(humanize.naturalsize))
        # time_ax.set_ylabel("time")

        mem_data_x, mem_data_y = [], []
        # query_time_x_data, query_time_y_data = [], []
        # burst_time_x_data, burst_time_y_data = [], []
        ekg_current_bytes_used_x, ekg_current_bytes_used_y = [], []
        ekg_mem_in_use_x, ekg_mem_in_use_y = [], []

        marker_x_data, marker_labels = [], []

        (mem_plt,) = mem_ax.plot_date(
            mem_data_x, mem_data_y, "-", label="mem_rss", color="black", linewidth=1
        )
        (ekg_current_bytes_used_plt,) = mem_ax.plot_date(
            ekg_current_bytes_used_x,
            ekg_current_bytes_used_y,
            "-",
            label="ekg_current_bytes_used",
            color="#0a7787", linewidth=1
        )
        (ekg_mem_in_use_plt,) = mem_ax.plot_date(
            ekg_mem_in_use_x,
            ekg_mem_in_use_y,
            "-",
            label="ekg_mem_in_use",
            color="#1c730d", linewidth=1
        )
        self.burst_start = 0
        # burst_time_plt, = mem_ax.plot_date(burst_time_x_data, burst_time_y_data, '-', label="burst time")
        # query_time_plt, = mem_ax.plot_date(query_time_x_data, query_time_y_data, '-', label="query time")

        def update(frame):
            while self.mem_q:
                evt = self.mem_q.pop(0)
                mem_data_x.append(evt.ts)
                mem_data_y.append(evt.data)
                mem_plt.set_data(mem_data_x, mem_data_y)

            if self.enable_ekg:
                while self.ekg_q:
                    evt = self.ekg_q.pop(0)
                    ekg_current_bytes_used_x.append(evt.ts)
                    ekg_current_bytes_used_y.append(
                        evt.data["rts"]["gc"]["current_bytes_used"]["val"]
                    )
                    ekg_current_bytes_used_plt.set_data(
                        ekg_current_bytes_used_x, ekg_current_bytes_used_y
                    )
                    ekg_mem_in_use_x.append(evt.ts)
                    ekg_mem_in_use_y.append(
                        evt.data["gcdetails_mem_in_use_bytes"]["val"]
                    )
                    ekg_mem_in_use_plt.set_data(
                        ekg_mem_in_use_x, ekg_mem_in_use_y
                    )

            while self.mem_instant_q:
                evt = self.mem_instant_q.pop(0)
                label = f"{humanize.naturalsize(evt.data)}"
                plt.text(evt.ts, evt.data, label, horizontalalignment='left', 
                        bbox={'facecolor': '#cccccc', 'linewidth': 0, 'alpha': 0.9})

            while self.q:
                evt = self.q.pop(0)
                if evt.typ == "burst_fin":
                    plt.axvline(
                        x=evt.ts, label=f"{evt.typ}", linewidth=1, color="#7bd487",
                        zorder=-1
                    )
                elif evt.typ == "query_fin":
                    plt.axvline(
                        x=evt.ts,
                        ymin=0.225,
                        ymax=0.275,
                        linewidth=1,
                        zorder=-2,
                        label=f"{evt.typ}",
                        color="#7bd487",
                    )

            while self.burst_span_q:
                evt = self.burst_span_q.pop(0)
                burst_start = evt[0]
                burst_end = evt[1]
                print(f"burst length: {burst_end - burst_start}")
                plt.axvline(burst_end, color="#8f8fff", linewidth=1, zorder=-3)
                plt.axvspan(burst_start, burst_end, color="#dfdfff", zorder=-3)

            # if not len(self.query_service_time_q) == 0:
            #     evt = self.query_service_time_q.pop(0)
            #     query_time_x_data.append(evt.ts)
            #     query_time_y_data.append(evt.data)
            #     query_time_plt.set_data(query_time_x_data, query_time_y_data)

            # if not len(self.burst_service_time_q) == 0:
            #     evt = self.burst_service_time_q.pop(0)
            #     burst_time_x_data.append(evt.ts)
            #     burst_time_y_data.append(evt.data)
            #     burst_time_plt.set_data(burst_time_x_data, burst_time_y_data)

            figure.gca().relim()
            figure.gca().autoscale_view()
            # return [mem_plt, query_time_plt, burst_time_plt]
            return [mem_plt, ekg_current_bytes_used_plt]

        ani = anim.FuncAnimation(figure, update, interval=500)
        p = mp.Process(target=self.run)
        p.start()
        plt.legend(loc="upper left")
        plt.grid(True)
        plt.show()
        p.join()


if __name__ == "__main__":
    hge_pid = int(sys.argv[2])
    config = toml.load(sys.argv[1])["stress"]
    print(config)
    # stress_test = StressTest(
    #     hge_pid=hge_pid,
    #     bursts_per_loop=7,
    #     mutations_per_burst=8,
    #     request_delay=0.5,
    #     burst_delay=20,
    #     loop_delay=30,
    #     loop_count=4,
    #     measurement_delay=0.5,
    # )
    stress_test = StressTest(
        hge_pid=hge_pid,
        **config,
    )
    stress_test.visualise()
