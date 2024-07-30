#!/bin/bash

# Function to convert bytes to megabytes
bytes_to_mb() {
    echo "scale=2; $1 / 1048576" | bc
}

# Function to perform the speed test
speed_test() {
    local test_file="speedtest_file"
    local file_size_mb=10000
    local file_size_bytes=$((file_size_mb * 1048576))

    echo "Performing disk speed test..."
    echo "Current working directory: $(pwd)"
    echo "Available disk space: $(df -h . | awk 'NR==2 {print $4}')"
    echo "Creating a ${file_size_mb}MB file for testing..."

    # Write speed test
    start_time=$(date +%s.%N)
    if ! dd if=/dev/zero of="$test_file" bs=1M count="$file_size_mb" 2>/dev/null; then
        echo "Error: Failed to create test file. Check permissions and available space."
        return 1
    fi
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc)
    
    if (( $(echo "$duration > 0" | bc -l) )); then
        write_speed=$(echo "scale=2; $file_size_bytes / $duration / 1048576" | bc)
        echo "Write speed: ${write_speed} MB/s"
    else
        echo "Write speed test completed too quickly to measure accurately."
    fi

    # Ensure the file exists before reading
    if [ -f "$test_file" ]; then
        echo "Test file size: $(du -h "$test_file" | cut -f1)"
        
        # Read speed test
        start_time=$(date +%s.%N)
        dd if="$test_file" of=/dev/null bs=1M 2>/dev/null
        end_time=$(date +%s.%N)
        duration=$(echo "$end_time - $start_time" | bc)
        
        if (( $(echo "$duration > 0" | bc -l) )); then
            read_speed=$(echo "scale=2; $file_size_bytes / $duration / 1048576" | bc)
            echo "Read speed: ${read_speed} MB/s"
        else
            echo "Read speed test completed too quickly to measure accurately."
        fi

        # Clean up
        rm "$test_file"
    else
        echo "Error: Test file was not created successfully."
        echo "Contents of current directory:"
        ls -la
    fi
}

# Run the speed test
speed_test