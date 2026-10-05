# Qualcomm Performance Skills

AI skills for memory, benchmarking, profiling, optimization, and system-performance analysis across Qualcomm platforms.

## Overview

This repository contains AI-powered skills for analyzing and optimizing system performance on Qualcomm platforms. The skills provide automated analysis, anomaly detection, and reporting capabilities for memory usage, kernel behavior, and userspace performance.

## Features

- **Memory Analysis**: Snapshot-based memory profiling and delta detection across AnonPages, Shmem, DMA-BUF, Slab, and more
- **Anomaly RCA**: Root cause analysis for memory anomalies
- **Kernel Diff Analysis**: Kernel-level memory change detection
- **Userspace Diff Analysis**: Userspace memory usage comparison
- **NHLOS Carveout Validation**: Non-HLOS memory carveout validation
- **Report Generation**: Automated HTML and JSON report generation
- **Snapshot Comparison**: Before/after memory snapshot comparison

## Repository Structure

```
memory-skills/
├── skills/          # AI skill definitions
├── internal/        # Internal analysis scripts
├── tests/           # Validation tests
└── common/          # Shared schemas and utilities
```

## Getting Started

### Prerequisites

See [memory-skills/requirements.txt](memory-skills/requirements.txt) for Python dependencies.

### Running Tests

```bash
cd memory-skills/tests
python run_validation.py --serial <adb_serial> --test all
```

See [memory-skills/tests/README.md](memory-skills/tests/README.md) for detailed test instructions.

## Documentation

- [Architecture](memory-skills/ARCHITECTURE.md)
- [Transport](memory-skills/TRANSPORT.md)
- [Troubleshooting](memory-skills/TROUBLESHOOTING.md)
- [Contributing](CONTRIBUTING.md)

## License

This project is licensed under the BSD-3-Clause License. See [LICENSE.txt](LICENSE.txt) for details.

Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.