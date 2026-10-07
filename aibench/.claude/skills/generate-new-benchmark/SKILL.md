---
name: generate-new-benchmark
description: Guides a non-technical user through adding a new benchmark tool to the aibench suite without writing code, by filling out a form that Claude turns into the required integration files.
category: Performance Benchmarking
---

# Non-Technical User Guide: Adding a New Benchmark

**For users with no coding experience**

This guide shows you how to add a new benchmark tool to the aibench suite in **15-20 minutes** without writing any code.

---

## What You'll Need

Before starting, gather this information about your benchmark tool:

- ✅ Benchmark name (e.g., "my_benchmark")
- ✅ What it measures (e.g., "CPU performance")
- ✅ Where it's installed on your device (e.g., "/usr/bin/my_benchmark")
- ✅ Sample output (run it once and copy the results)
- ✅ What the numbers mean (e.g., "higher is better")

**Time Required:** 5 minutes to gather information

---

## Step-by-Step Process

### Step 1: Gather Benchmark Information (5 minutes)

Run your benchmark tool once and save the output. For example:

```
$ /usr/bin/my_benchmark
Score: 12345.67 iterations/sec
Completed in 45 seconds
```

Write down:
- The benchmark name
- What it measures
- The executable path
- The output you see
- Which numbers are important

---

### Step 2: Fill Out the Integration Form (2 minutes)

Copy this template and fill in your information:

```markdown
# New Benchmark Integration Request

## Benchmark Information
- **Name:** [your_benchmark_name]
- **Description:** [what it measures, e.g., "Measures CPU performance"]
- **Executable Path:** [path on device, e.g., "/usr/bin/my_benchmark"]
- **Category:** [CPU, Memory, Storage, GPU, or OS]

## Sample Output
[Paste the output from running your benchmark]

## Metrics
- **Metric Name:** [e.g., "score"]
- **Unit:** [e.g., "iterations/sec"]
- **Higher/Lower is Better:** [higher or lower]
- **Expected Range:** [e.g., "10000-15000"]

## Test Variants (Optional)
- [variant_name]: [description]
```

**Example (filled out):**

```markdown
# New Benchmark Integration Request

## Benchmark Information
- **Name:** my_benchmark
- **Description:** Measures CPU performance
- **Executable Path:** /usr/bin/my_benchmark
- **Category:** CPU

## Sample Output
Score: 12345.67 iterations/sec
Completed in 45 seconds

## Metrics
- **Metric Name:** score
- **Unit:** iterations/sec
- **Higher/Lower is Better:** higher
- **Expected Range:** 10000-15000

## Test Variants (Optional)
- default: Standard test
- intensive: High-load test
```

---

### Step 3: Ask Claude to Generate Files (1 minute)

Open Claude and paste your filled-out form with this request:

> "I have a new benchmark tool. Here's the information about it:
> 
> [paste your filled form here]
> 
> Can you generate all the files needed to integrate it into the aibench suite?"

---

### Step 4: Claude Generates Everything (5-10 minutes)

Claude will automatically:

1. ✅ Analyze your benchmark information
2. ✅ Extract metrics from your sample output
3. ✅ Generate Python code files
4. ✅ Generate configuration files
5. ✅ Generate test files
6. ✅ Generate documentation
7. ✅ Validate everything
8. ✅ Place files in correct locations

**You don't need to do anything during this step - just wait!**

---

### Step 5: Review the Results (2 minutes)

Claude will show you:

**Generated Files:**
- `src/benchmark/your_benchmark.py` - Main benchmark code
- `src/reporting/outlier_detector_your_benchmark.py` - Statistical analysis
- `tests/test_your_benchmark.py` - Automated tests
- `config/benchmarks.yaml` - Configuration (updated)
- `.claude/skills/run-your_benchmark/SKILL.md` - Documentation

**Validation Report:**
```
✅ All files generated successfully
✅ Python syntax valid
✅ Configuration valid
✅ Auto-discovery test passed
✅ Ready for integration
```

**Integration Status:**
```
✅ Files placed in correct locations
✅ Configuration updated
✅ Registry can discover benchmark
✅ Integration successful
```

---

### Step 6: Verify Integration (1 minute)

Claude will provide a simple verification command. Copy and paste it:

```bash
cd aibench
python -c "from src.benchmark.registry import BenchmarkRegistry; BenchmarkRegistry.auto_discover(); print('your_benchmark' in BenchmarkRegistry.list_all())"
```

**Expected Output:**
```
True
```

If you see `True`, your benchmark is successfully integrated!

---

### Step 7: Test Your Benchmark (2 minutes)

Run your benchmark using Claude:

> "Run my_benchmark over ssh"

Claude will execute your benchmark and show you the results.

---

## Complete Timeline

| Step | Time | What You Do |
|------|------|-------------|
| 1. Gather info | 5 min | Run benchmark, note output |
| 2. Fill form | 2 min | Copy template, fill in details |
| 3. Ask Claude | 1 min | Paste form, ask for generation |
| 4. Wait | 5-10 min | Claude generates everything |
| 5. Review | 2 min | Check validation report |
| 6. Verify | 1 min | Run verification command |
| 7. Test | 2 min | Run benchmark via Claude |
| **Total** | **15-20 min** | **Minimal effort required** |

---

## What If Something Goes Wrong?

### Issue: Claude says "Missing information"

**Solution:** Fill in the missing fields in your form and ask again.

### Issue: Validation fails

**Solution:** Claude will tell you exactly what's wrong and how to fix it. Usually it's:
- Incorrect executable path
- Sample output format unclear
- Metric name not found in output

### Issue: Verification command returns False

**Solution:** Ask Claude:
> "The verification failed. Can you check what went wrong and fix it?"

Claude will diagnose and fix the issue.

---

## Example: Complete Workflow

**User:** "I have a benchmark called 'memtest' that measures memory bandwidth. When I run it, I get: 'Bandwidth: 45.67 GB/sec'. Can you help me integrate it?"

**Claude:** "I'll help you integrate memtest. Let me generate all the required files..."

[5 minutes later]

**Claude:** "✅ All files generated and validated. Your benchmark is ready! Here's the verification command..."

**User:** [Runs verification command]

**Output:** `True`

**User:** "Run memtest over ssh"

**Claude:** [Executes benchmark and shows results]

**Result:** Benchmark integrated in 15 minutes, zero coding required!

---

## Frequently Asked Questions

### Q: Do I need to know Python?
**A:** No! Claude writes all the code for you.

### Q: Do I need to understand the aibench suite architecture?
**A:** No! Claude handles all the technical details.

### Q: What if I make a mistake in the form?
**A:** Claude will ask for clarification or suggest corrections.

### Q: Can I modify the generated files later?
**A:** Yes, but you can also ask Claude to regenerate with changes.

### Q: What if my benchmark has complex output?
**A:** Claude can handle complex outputs. Just provide a sample and Claude will extract the metrics.

### Q: How do I know if it worked?
**A:** Claude provides validation reports and verification commands to confirm success.

### Q: Can I add multiple benchmarks?
**A:** Yes! Repeat the process for each benchmark.

### Q: What if I need help?
**A:** Ask Claude! Claude can troubleshoot issues and provide guidance.

---

## Tips for Success

1. **Provide complete sample output** - Include all the text your benchmark produces
2. **Be specific about metrics** - Clearly identify which numbers are important
3. **Test your benchmark first** - Make sure it runs on your device before integrating
4. **Ask Claude for help** - If anything is unclear, just ask!
5. **Review the validation report** - It tells you if everything is correct

---

## What You Get

After following this guide, you'll have:

✅ **Fully integrated benchmark** - Ready to use  
✅ **Automated tests** - Ensures reliability  
✅ **Documentation** - For future reference  
✅ **Dashboard integration** - Visual results  
✅ **Validation** - Confirmed working  
✅ **Claude support** - Can run via natural language prompts

---

## Next Steps

Once your benchmark is integrated:

1. **Run it:** Ask Claude to "run [your_benchmark] over ssh"
2. **View results:** Check the dashboard at `output/reports/index.html`
3. **Compare runs:** Run multiple times to see trends
4. **Share:** Your benchmark is now available to the whole team

---

## Summary

**For non-technical users:**
- ✅ No coding required
- ✅ Simple form to fill out
- ✅ Claude does all the work
- ✅ 15-20 minutes total time
- ✅ Validation confirms success
- ✅ Full support from Claude

**You can integrate benchmarks without any technical knowledge!**

---

## Need Help?

If you have questions or run into issues:

1. **Ask Claude** - Claude can troubleshoot and help
2. **Check the validation report** - It shows exactly what's wrong
3. **Review the troubleshooting guide** - Common issues and solutions
4. **Contact support** - Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

---

**Remember:** You don't need to be technical to use this system. Claude handles all the complexity for you!