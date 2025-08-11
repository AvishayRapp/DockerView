### **Docker TUI: System & Container Monitor**

This is a terminal-based UI (TUI) for monitoring system resources and managing Docker containers. It provides a clean, real-time view of your running and stopped containers, along with key system metrics like CPU and RAM usage.

-----

### **Features**

  * **Real-time Monitoring:** Displays host system CPU and RAM usage with dynamic bar graphs.
  * **Container Status:** Lists all Docker containers, showing their ID, name, image, port mappings, and current status.
  * **Resource Usage per Container:** Shows the real-time **RAM** usage for each container.
  * **Container Management:** Easily start, stop, restart, rename, or delete containers with simple keyboard shortcuts.
  * **Uptime Display:** Provides a clear, formatted uptime for all running containers.
  * **Intuitive Interface:** A simple, `curses`-based TUI that is easy to navigate and read.

-----

### **Prerequisites**

To run this script, you need to have the following installed on your system:

  * **Python 3.6+**
  * **Docker**
  * **Docker SDK for Python:** `pip install docker`
  * **psutil:** `pip install psutil`

Additionally, since the script uses `iptables` as a fallback method to discover host port mappings, you may need to run it with `sudo` permissions on Linux systems if your user doesn't have direct access to `iptables`.

-----

### **Installation & Usage**

1.  **Save the script:** Save the provided Python code to a file named `monitor.py`.
2.  **Make it executable:**
    ```bash
    chmod +x monitor.py
    ```
3.  **Run the script:**
    ```bash
    ./monitor.py
    ```

If you encounter a `PermissionError` when trying to view port mappings, you may need to run it with `sudo`:

```bash
sudo ./monitor.py
```

-----

### **Key Bindings**

| Key | Action |
| :-- | :--- |
| **↑ / ↓** | Navigate through the container list |
| **U** | Update the list of containers |
| **S** | Start the selected container |
| **X** | Stop the selected container |
| **R** | Restart the selected container |
| **N** | Rename the selected container |
| **D** | Delete the selected container (requires confirmation) |
| **Q** | Quit the application |

-----

### **How It Works**

The script leverages the **Docker SDK for Python** and the **psutil** library to gather information. The main application loop uses the `curses` library to draw a dynamic, interactive interface in the terminal. It fetches container data, calculates resource usage, and refreshes the display every second to provide a live view of your system and containers.

  * `get_cpu_usage()` and `get_ram_usage()` fetch system-wide resource metrics.
  * `get_docker_containers()` iterates through all containers, pulling their status, image, and port information.
  * `_get_container_ram_stats()` extracts the memory usage for each individual container.
  * The `_perform_action()` function handles all the container management commands like start, stop, and delete.

Feel free to modify the script to fit your specific needs or add new features\!
