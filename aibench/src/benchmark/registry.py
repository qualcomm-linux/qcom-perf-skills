"""
Benchmark registry for static discovery and instantiation.
Provides factory interface for explicitly registered benchmarks.
"""

from typing import Type, Dict

from src.utils.logger import phase_logger

# Import all benchmark classes explicitly
from src.benchmark.coremark import BENCHMARK_CLASS as CoremarkBenchmark
from src.benchmark.sysbench import BENCHMARK_CLASS as SysbenchBenchmark
from src.benchmark.hackbench import BENCHMARK_CLASS as HackbenchBenchmark
from src.benchmark.tiobench import BENCHMARK_CLASS as TiobenchBenchmark
from src.benchmark.glmark2 import BENCHMARK_CLASS as Glmark2Benchmark
from src.benchmark.coremark_pro import BENCHMARK_CLASS as CoremarkProBenchmark
from src.benchmark.osbench import BENCHMARK_CLASS as OSBenchBenchmark
from src.benchmark.ramspeed import BENCHMARK_CLASS as RAMSpeedBenchmark
from src.benchmark.unixbench import BENCHMARK_CLASS as UnixBenchBenchmark
from src.benchmark.bw_mem import BENCHMARK_CLASS as BwMemBenchmark
from src.benchmark.lat_mem_rd import BENCHMARK_CLASS as LatMemRdBenchmark
from src.benchmark.geekbench import BENCHMARK_CLASS as GeekbenchBenchmark

class BenchmarkRegistry:
    _registry: Dict[str, Type] = {
        "coremark": CoremarkBenchmark,
        "sysbench": SysbenchBenchmark,
        "hackbench": HackbenchBenchmark,
        "tiobench": TiobenchBenchmark,
        "glmark2": Glmark2Benchmark,
        "coremark_pro": CoremarkProBenchmark,
        "osbench": OSBenchBenchmark,
        "ramspeed": RAMSpeedBenchmark,
        "unixbench": UnixBenchBenchmark,
        "bw_mem": BwMemBenchmark,
        "lat_mem_rd": LatMemRdBenchmark,
        "geekbench": GeekbenchBenchmark,
    }
    
    @classmethod
    def register(cls, name: str, benchmark_class: Type):
        """Manually register a benchmark"""
        cls._registry[name] = benchmark_class
    
    @classmethod
    def get(cls, name: str) -> Type:
        """Get benchmark class by name"""
        return cls._registry.get(name)
    
    @classmethod
    def list_all(cls) -> Dict[str, Type]:
        """List all registered benchmarks"""
        return cls._registry