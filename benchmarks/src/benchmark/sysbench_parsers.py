"""
sysbench_parsers.py - Dedicated parser units for sysbench benchmark categories

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from typing import Dict, Any
from src.benchmark.sysbench import SysbenchIterationResult

class BaseSysbenchParser:
    """Base class with common parsing utilities for sysbench output"""
    
    @staticmethod
    def extract_general_stats(content: str) -> Dict[str, float]:
        """Extract total time and total events from General statistics section"""
        stats = {}
        
        # Pattern: "total time:                          10.0019s"
        match_time = re.search(r'total time:\s+([\d.]+)s', content)
        if match_time:
            stats['total_time_sec'] = float(match_time.group(1))
        
        # Pattern: "total number of events:              92066"
        match_events = re.search(r'total number of events:\s+(\d+)', content)
        if match_events:
            stats['total_events'] = int(match_events.group(1))
        
        return stats
    
    @staticmethod
    def extract_latency_metrics(content: str) -> Dict[str, float]:
        """Extract latency metrics from Latency (ms) section"""
        latency = {}
        
        # Pattern: "min:                                    0.41"
        match_min = re.search(r'min:\s+([\d.]+)', content)
        if match_min:
            latency['latency_min_ms'] = float(match_min.group(1))
        
        # Pattern: "avg:                                    0.87"
        match_avg = re.search(r'avg:\s+([\d.]+)', content)
        if match_avg:
            latency['latency_avg_ms'] = float(match_avg.group(1))
        
        # Pattern: "max:                                   12.67"
        match_max = re.search(r'max:\s+([\d.]+)', content)
        if match_max:
            latency['latency_max_ms'] = float(match_max.group(1))
        
        # Pattern: "95th percentile:                        4.03"
        match_p95 = re.search(r'95th percentile:\s+([\d.]+)', content)
        if match_p95:
            latency['latency_95_ms'] = float(match_p95.group(1))
        
        # Pattern: "sum:                                79960.32"
        match_sum = re.search(r'sum:\s+([\d.]+)', content)
        if match_sum:
            latency['latency_sum_ms'] = float(match_sum.group(1))
        
        return latency
    
    @staticmethod
    def extract_fairness_metrics(content: str) -> Dict[str, float]:
        """Extract fairness metrics from Threads fairness section"""
        fairness = {}
        
        # Pattern: "events (avg/stddev):           11508.2500/180.89"
        match_events = re.search(r'events \(avg/stddev\):\s+([\d.]+)/([\d.]+)', content)
        if match_events:
            fairness['events_avg'] = float(match_events.group(1))
            fairness['events_stddev'] = float(match_events.group(2))
        
        # Pattern: "execution time (avg/stddev):   9.9950/0.00"
        match_exec = re.search(r'execution time \(avg/stddev\):\s+([\d.]+)/([\d.]+)', content)
        if match_exec:
            fairness['execution_time_avg_sec'] = float(match_exec.group(1))
            fairness['execution_time_stddev_sec'] = float(match_exec.group(2))
        
        return fairness


class ThreadsParser(BaseSysbenchParser):
    """Parse sysbench threads scheduler test output"""
    
    @staticmethod
    def parse(content: str, test_name: str) -> SysbenchIterationResult:
        result = SysbenchIterationResult(test_name=test_name, category='threads', raw_output=content)
        
        # Extract general stats
        general = BaseSysbenchParser.extract_general_stats(content)
        result.total_time_sec = general.get('total_time_sec', 0.0)
        result.total_events = int(general.get('total_events', 0))
        
        # Extract latency metrics
        latency = BaseSysbenchParser.extract_latency_metrics(content)
        result.latency_min_ms = latency.get('latency_min_ms', 0.0)
        result.latency_avg_ms = latency.get('latency_avg_ms', 0.0)
        result.latency_max_ms = latency.get('latency_max_ms', 0.0)
        result.latency_95_ms = latency.get('latency_95_ms', 0.0)
        result.latency_sum_ms = latency.get('latency_sum_ms', 0.0)
        
        # Extract fairness metrics
        fairness = BaseSysbenchParser.extract_fairness_metrics(content)
        result.events_avg = fairness.get('events_avg', 0.0)
        result.events_stddev = fairness.get('events_stddev', 0.0)
        result.execution_time_avg_sec = fairness.get('execution_time_avg_sec', 0.0)
        result.execution_time_stddev_sec = fairness.get('execution_time_stddev_sec', 0.0)
        
        # Calculate throughput (events/sec)
        match_speed = re.search(r'events per second:\s+([\d.]+)', content)
        if match_speed:
            result.throughput = float(match_speed.group(1))
        elif result.total_time_sec > 0:
            result.throughput = result.total_events / result.total_time_sec
            
        return result


class MutexParser(BaseSysbenchParser):
    """Parse sysbench mutex contention test output"""
    
    @staticmethod
    def parse(content: str, test_name: str) -> SysbenchIterationResult:
        result = SysbenchIterationResult(test_name=test_name, category='mutex', raw_output=content)
        
        # Extract general stats
        general = BaseSysbenchParser.extract_general_stats(content)
        result.total_time_sec = general.get('total_time_sec', 0.0)
        result.total_events = int(general.get('total_events', 0))
        
        # Extract latency metrics
        latency = BaseSysbenchParser.extract_latency_metrics(content)
        result.latency_min_ms = latency.get('latency_min_ms', 0.0)
        result.latency_avg_ms = latency.get('latency_avg_ms', 0.0)
        result.latency_max_ms = latency.get('latency_max_ms', 0.0)
        result.latency_95_ms = latency.get('latency_95_ms', 0.0)
        result.latency_sum_ms = latency.get('latency_sum_ms', 0.0)
        
        # Extract fairness metrics
        fairness = BaseSysbenchParser.extract_fairness_metrics(content)
        result.events_avg = fairness.get('events_avg', 0.0)
        result.events_stddev = fairness.get('events_stddev', 0.0)
        result.execution_time_avg_sec = fairness.get('execution_time_avg_sec', 0.0)
        result.execution_time_stddev_sec = fairness.get('execution_time_stddev_sec', 0.0)
        
        # Calculate throughput (events/sec)
        match_speed = re.search(r'events per second:\s+([\d.]+)', content)
        if match_speed:
            result.throughput = float(match_speed.group(1))
        elif result.total_time_sec > 0:
            result.throughput = result.total_events / result.total_time_sec
            
        return result


class MemoryParser(BaseSysbenchParser):
    """Parse sysbench memory test output"""
    
    @staticmethod
    def parse(content: str, test_name: str) -> SysbenchIterationResult:
        result = SysbenchIterationResult(test_name=test_name, category='memory', raw_output=content)
        
        # Extract general stats
        general = BaseSysbenchParser.extract_general_stats(content)
        result.total_time_sec = general.get('total_time_sec', 0.0)
        result.total_events = int(general.get('total_events', 0))
        
        # Extract latency metrics
        latency = BaseSysbenchParser.extract_latency_metrics(content)
        result.latency_min_ms = latency.get('latency_min_ms', 0.0)
        result.latency_avg_ms = latency.get('latency_avg_ms', 0.0)
        result.latency_max_ms = latency.get('latency_max_ms', 0.0)
        result.latency_95_ms = latency.get('latency_95_ms', 0.0)
        result.latency_sum_ms = latency.get('latency_sum_ms', 0.0)
        
        # Extract fairness metrics
        fairness = BaseSysbenchParser.extract_fairness_metrics(content)
        result.events_avg = fairness.get('events_avg', 0.0)
        result.events_stddev = fairness.get('events_stddev', 0.0)
        result.execution_time_avg_sec = fairness.get('execution_time_avg_sec', 0.0)
        result.execution_time_stddev_sec = fairness.get('execution_time_stddev_sec', 0.0)
        
        # Extract memory-specific metrics
        match_ops = re.search(r'Total operations:\s+[\d,]+\s+\(([\d.]+)\s+per second\)', content)
        if match_ops:
            result.operations_per_sec = float(match_ops.group(1))
            
        match_transfer = re.search(r'([\d.]+)\s+MiB transferred\s+\(([\d.]+)\s+MiB/sec\)', content)
        if match_transfer:
            result.data_transferred_mib = float(match_transfer.group(1))
            result.throughput = float(match_transfer.group(2))  # MiB/sec
            
        return result


class CPUParser(BaseSysbenchParser):
    """Parse sysbench CPU test output"""
    
    @staticmethod
    def parse(content: str, test_name: str) -> SysbenchIterationResult:
        result = SysbenchIterationResult(test_name=test_name, category='cpu', raw_output=content)
        
        # Extract general stats
        general = BaseSysbenchParser.extract_general_stats(content)
        result.total_time_sec = general.get('total_time_sec', 0.0)
        result.total_events = int(general.get('total_events', 0))
        
        # Extract latency metrics
        latency = BaseSysbenchParser.extract_latency_metrics(content)
        result.latency_min_ms = latency.get('latency_min_ms', 0.0)
        result.latency_avg_ms = latency.get('latency_avg_ms', 0.0)
        result.latency_max_ms = latency.get('latency_max_ms', 0.0)
        result.latency_95_ms = latency.get('latency_95_ms', 0.0)
        result.latency_sum_ms = latency.get('latency_sum_ms', 0.0)
        
        # Extract fairness metrics
        fairness = BaseSysbenchParser.extract_fairness_metrics(content)
        result.events_avg = fairness.get('events_avg', 0.0)
        result.events_stddev = fairness.get('events_stddev', 0.0)
        result.execution_time_avg_sec = fairness.get('execution_time_avg_sec', 0.0)
        result.execution_time_stddev_sec = fairness.get('execution_time_stddev_sec', 0.0)
        
        # Extract CPU throughput
        match_speed = re.search(r'events per second:\s+([\d.]+)', content)
        if match_speed:
            result.throughput = float(match_speed.group(1))
        elif result.total_time_sec > 0:
            result.throughput = result.total_events / result.total_time_sec
            
        return result


class FileIOParser(BaseSysbenchParser):
    """Parse sysbench fileio test output"""
    
    @staticmethod
    def parse(content: str, test_name: str) -> SysbenchIterationResult:
        result = SysbenchIterationResult(test_name=test_name, category='fileio', raw_output=content)
        
        # Extract general stats
        general = BaseSysbenchParser.extract_general_stats(content)
        result.total_time_sec = general.get('total_time_sec', 0.0)
        result.total_events = int(general.get('total_events', 0))
        
        # Extract latency metrics
        latency = BaseSysbenchParser.extract_latency_metrics(content)
        result.latency_min_ms = latency.get('latency_min_ms', 0.0)
        result.latency_avg_ms = latency.get('latency_avg_ms', 0.0)
        result.latency_max_ms = latency.get('latency_max_ms', 0.0)
        result.latency_95_ms = latency.get('latency_95_ms', 0.0)
        result.latency_sum_ms = latency.get('latency_sum_ms', 0.0)
        
        # Extract fairness metrics
        fairness = BaseSysbenchParser.extract_fairness_metrics(content)
        result.events_avg = fairness.get('events_avg', 0.0)
        result.events_stddev = fairness.get('events_stddev', 0.0)
        result.execution_time_avg_sec = fairness.get('execution_time_avg_sec', 0.0)
        result.execution_time_stddev_sec = fairness.get('execution_time_stddev_sec', 0.0)
        
        # Extract FileIO specific metrics
        # The sysbench output might vary. It can show "read, MiB/s: X", "written, MiB/s: X", or both.
        # Fallback to general read/written parsing regardless of test_name to be robust.
        
        match_read = re.search(r'read,\s+MiB/s:\s+([\d.]+)', content)
        if match_read:
            result.read_mib_sec = float(match_read.group(1))
            
        match_write = re.search(r'written,\s+MiB/s:\s+([\d.]+)', content)
        if match_write:
            result.write_mib_sec = float(match_write.group(1))
            
        # Determine throughput based on test name
        test_name_lower = test_name.lower()
        if 'mixed' in test_name_lower or 'rw' in test_name_lower:
            # For mixed tests, throughput is sum of read and write
            result.throughput = result.read_mib_sec + result.write_mib_sec
        elif 'read' in test_name_lower:
            result.throughput = result.read_mib_sec
        elif 'write' in test_name_lower:
            result.throughput = result.write_mib_sec
        else:
            # Fallback if name is ambiguous
            result.throughput = max(result.read_mib_sec, result.write_mib_sec)
                
        return result
