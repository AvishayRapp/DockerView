#!/usr/bin/env python3

import curses
import docker
import psutil
import time
import subprocess
import re
from datetime import datetime
from typing import List, Dict, Any

class SystemMonitor:
    """
    A terminal-based system and Docker container monitor using curses.
    """
    def __init__(self):
        self.docker_client = None
        self.docker_error = None
        try:
            self.docker_client = docker.from_env(timeout=2)
            self.docker_client.ping() # Check for connection
        except Exception as e:
            self.docker_error = f"Docker not available: {str(e)}"

        self.selected_index = 0
        self.scroll_pos = 0
        self.status_message = ""
        self.total_cpus = psutil.cpu_count(logical=False)

    # --- Data Fetching ---

    def get_cpu_usage(self) -> float:
        """Returns CPU usage percentage."""
        return psutil.cpu_percent(interval=0.1)

    def get_ram_usage(self):
        """Returns RAM usage statistics object."""
        return psutil.virtual_memory()

    def _get_host_port_from_iptables(self, container_ip: str, container_i_port: str) -> str:
        """
        FALLBACK METHOD: Uses `iptables-save` to find the host port.
        Requires `sudo` and is a Linux-specific method.
        """
        if not container_ip or not container_i_port:
            return 'N/A'

        try:
            # We look for rules that DNAT (Destination NAT) to the container's IP and port
            # The format is often like `DNAT to:172.17.0.2:80`
            command = f"sudo iptables-save | grep 'DNAT.*--to-destination {container_ip}:{container_i_port}'"
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
            output = result.stdout

            if output:
                # The rule will also contain the host port (e.g., `-A DOCKER ! -i docker0 -p tcp -m tcp --dport 54772 ...`)
                match = re.search(r'--dport\s+(\d+)', output)
                if match:
                    return match.group(1)
        except subprocess.CalledProcessError:
            # This is expected if the grep finds no results
            pass
        except Exception:
            return 'Error'
        
        return 'N/A'
    
    def _get_container_uptime(self, container) -> str:
        """Calculates and formats the container's uptime."""
        try:
            status = container.status
            if status == 'running':
                started_at_str = container.attrs['State']['StartedAt']
                started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                now = datetime.now().astimezone(started_at.tzinfo)
                uptime_delta = now - started_at
                
                total_seconds = int(uptime_delta.total_seconds())
                days, remainder = divmod(total_seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                uptime_parts = []
                if days > 0:
                    uptime_parts.append(f"{days}d")
                if hours > 0:
                    uptime_parts.append(f"{hours}h")
                if minutes > 0:
                    uptime_parts.append(f"{minutes}m")
                if not uptime_parts and seconds >= 0:
                    uptime_parts.append(f"{seconds}s")
                
                return "".join(uptime_parts)
            else:
                return 'N/A'
        except (KeyError, ValueError):
            return 'Error'

    def _get_container_ram_stats(self, container_obj):
        """Calculates RAM usage for a given container object."""
        mem_usage_gb = 'N/A'
        try:
            stats = container_obj.stats(stream=False)
            
            # --- RAM Usage Calculation ---
            mem_usage_bytes = stats['memory_stats']['usage']
            mem_usage_gb = f"{mem_usage_bytes / (1024**3):.2f}G"

        except Exception:
            pass # Keep previous 'N/A' values
        
        return mem_usage_gb

    def get_docker_containers(self) -> List[Dict[str, Any]]:
        """
        Gathers container information using a reliable hybrid approach.
        """
        if self.docker_error:
            return []
        
        containers = []
        try:
            for container in self.docker_client.containers.list(all=True):
                attrs = container.attrs
                
                ports = 'N/A'
                ip_addr = 'N/A'

                # --- Step 1: Get IP address from NetworkSettings (needed for iptables fallback) ---
                networks = attrs.get('NetworkSettings', {}).get('Networks', {})
                for network_name, network_info in networks.items():
                    if network_info.get('IPAddress'):
                        ip_addr = network_info['IPAddress']
                        break

                # --- Step 2: Get ports from the container's attributes ---
                port_data = attrs.get('NetworkSettings', {}).get('Ports', {})
                if port_data:
                    port_list = []
                    for container_port_key, host_ports_info in port_data.items():
                        container_i_port = container_port_key.split('/')[0]
                        
                        host_port_num = 'N/A'
                        if host_ports_info and len(host_ports_info) > 0:
                            host_port_binding = host_ports_info[0]
                            host_port_num = host_port_binding.get('HostPort', 'N/A')
                        
                        # --- Step 3: Use iptables fallback if host port is still 'N/A' ---
                        if host_port_num == 'N/A':
                           host_port_num = self._get_host_port_from_iptables(ip_addr, container_i_port)
                        
                        # --- Step 4: Format the port string cleanly ---
                        if host_port_num != 'N/A':
                            port_list.append(f"{host_port_num}->{container_i_port}")
                        else:
                            port_list.append(f"{container_i_port}")
                            
                    ports = ",".join(port_list)
                
                ram_usage = self._get_container_ram_stats(container)

                containers.append({
                    'id': container.short_id,
                    'name': container.name,
                    'status': container.status,
                    'image': container.image.tags[0] if container.image.tags else container.image.short_id,
                    'ports': ports,
                    'uptime': self._get_container_uptime(container),
                    'ram': ram_usage,
                    'obj': container
                })
        except Exception as e:
            self.docker_error = f"Docker error: {str(e)}"
            return []
            
        return sorted(containers, key=lambda c: c['name'])


    # --- Container Actions ---
    
    def _perform_action(self, action_name: str, containers: List[Dict], new_name: str = None):
        if not containers or self.docker_error:
            return

        container_obj = containers[self.selected_index]['obj']
        
        try:
            if action_name == 'rename':
                container_obj.rename(new_name)
                self.status_message = f"Successfully renamed {container_obj.name} to {new_name}."
            elif action_name == 'remove':
                container_obj.remove(force=True)
                self.status_message = f"Successfully removed container {container_obj.name}."
            elif action_name in ['start', 'stop', 'restart']:
                action_func = getattr(container_obj, action_name, None)
                if action_func:
                    action_func()
                    self.status_message = f"Successfully sent '{action_name}' command to {container_obj.name}."
            else:
                self.status_message = f"Action '{action_name}' not available for this container."
        except Exception as e:
            self.status_message = f"Error: {str(e)}"


    def _confirm_action(self, stdscr, message: str) -> bool:
        """Draws a confirmation window and waits for user input."""
        height, width = stdscr.getmaxyx()
        win_h, win_w = 5, 50
        start_y, start_x = (height - win_h) // 2, (width - win_w) // 2
        
        confirm_win = curses.newwin(win_h, win_w, start_y, start_x)
        confirm_win.box()
        confirm_win.addstr(1, 2, message, curses.A_BOLD)
        confirm_win.addstr(2, 2, "Are you sure? (YES/no): ")
        confirm_win.refresh()
        
        curses.echo()
        curses.curs_set(1)
        
        user_input = ""
        while True:
            try:
                user_input = confirm_win.getstr(2, 26, 10).decode('utf-8').strip().lower()
                break
            except curses.error:
                confirm_win.addstr(2, 26, " " * 10)
                confirm_win.refresh()
        
        curses.noecho()
        curses.curs_set(0)
        
        confirm_win.clear()
        confirm_win.refresh()
        
        return user_input in ['yes', 'y']

    def _get_new_name(self, stdscr, current_name: str) -> str:
        """Draws an input window for the new container name."""
        height, width = stdscr.getmaxyx()
        win_h, win_w = 5, 50
        start_y, start_x = (height - win_h) // 2, (width - win_w) // 2
        
        input_win = curses.newwin(win_h, win_w, start_y, start_x)
        input_win.box()
        input_win.addstr(1, 2, "Rename container", curses.A_BOLD)
        input_win.addstr(2, 2, f"New name for '{current_name}': ")
        input_win.refresh()
        
        curses.echo()
        curses.curs_set(1)
        
        new_name = ""
        while True:
            try:
                new_name = input_win.getstr(2, 30, 20).decode('utf-8').strip()
                break
            except curses.error:
                input_win.addstr(2, 30, " " * 20)
                input_win.refresh()

        curses.noecho()
        curses.curs_set(0)
        
        input_win.clear()
        input_win.refresh()
        
        return new_name

    # --- UI Drawing ---

    def _setup_colors(self):
        """Initializes color pairs for the UI."""
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(6, curses.COLOR_GREEN, curses.COLOR_BLUE)
        curses.init_pair(7, curses.COLOR_RED, curses.COLOR_BLUE)
        curses.init_pair(8, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_BLUE) # CPU Bar
        curses.init_pair(10, curses.COLOR_WHITE, curses.COLOR_GREEN) # RAM Bar


    def _draw_header(self, stdscr, width: int):
        """Draws the top header with the title and timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = "System & Docker Monitor"
        header_text = f"{title} - {timestamp}"
        stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
        stdscr.addstr(0, (width - len(header_text)) // 2, header_text)
        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)

    def _draw_system_stats(self, stdscr, width: int):
        """Draws the CPU and RAM statistics section."""
        stats_win = stdscr.subwin(5, width, 2, 0)
        stats_win.box()
        stats_win.addstr(0, 2, "[ System Resources ]", curses.color_pair(4) | curses.A_BOLD)
        
        # Determine consistent bar width
        cpu_label_text = f"CPU Usage ({self.total_cpus} cores): "
        ram_text_part = f"RAM Usage: {self.get_ram_usage().used/1e9:0.2f}G / {self.get_ram_usage().total/1e9:0.2f}G"
        
        # The bar length will be the remaining width minus a fixed padding.
        # This makes the bars the same length regardless of the label text size.
        bar_start_x = max(len(cpu_label_text), len(ram_text_part)) + 4
        bar_width = width - bar_start_x - 15

        # CPU
        cpu_percent = self.get_cpu_usage()
        stats_win.addstr(2, 2, cpu_label_text.ljust(bar_start_x))
        
        # Color the CPU bar
        stats_win.addstr(2, bar_start_x, "|", curses.A_NORMAL)
        stats_win.addstr(2, bar_start_x + 1, ' ' * int(bar_width * cpu_percent / 100), curses.color_pair(9))
        stats_win.addstr(2, bar_start_x + 1 + int(bar_width * cpu_percent / 100), ' ' * (bar_width - int(bar_width * cpu_percent / 100)), curses.A_NORMAL)
        stats_win.addstr(2, bar_start_x + bar_width + 1, "|", curses.A_NORMAL)
        stats_win.addstr(2, bar_start_x + bar_width + 3, f"{cpu_percent:5.1f}%", curses.A_NORMAL)


        # RAM
        mem = self.get_ram_usage()
        ram_percent = mem.percent
        stats_win.addstr(3, 2, ram_text_part.ljust(bar_start_x))
        
        # Color the RAM bar
        stats_win.addstr(3, bar_start_x, "|", curses.A_NORMAL)
        stats_win.addstr(3, bar_start_x + 1, ' ' * int(bar_width * ram_percent / 100), curses.color_pair(10))
        stats_win.addstr(3, bar_start_x + 1 + int(bar_width * ram_percent / 100), ' ' * (bar_width - int(bar_width * ram_percent / 100)), curses.A_NORMAL)
        stats_win.addstr(3, bar_start_x + bar_width + 1, "|", curses.A_NORMAL)
        stats_win.addstr(3, bar_start_x + bar_width + 3, f"{ram_percent:5.1f}%", curses.A_NORMAL)

        stats_win.refresh()
        
    def _draw_container_list(self, stdscr, height: int, width: int, containers: List[Dict]):
        """Draws the scrollable list of Docker containers."""
        list_win = stdscr.subwin(height - 9, width, 8, 0)
        list_win.erase()
        list_win.box()
        list_win.addstr(0, 2, "[ Docker Containers ]", curses.color_pair(4) | curses.A_BOLD)

        if self.docker_error:
            list_win.addstr(2, 2, self.docker_error, curses.color_pair(2))
            list_win.refresh()
            return
            
        if not containers:
            list_win.addstr(2, 2, "No Docker containers found.")
            list_win.refresh()
            return

        # Define column widths
        ID_WIDTH = 12
        NAME_WIDTH = 20
        IMAGE_WIDTH = 30
        PORT_WIDTH = 6
        STATUS_WIDTH = 10
        UPTIME_WIDTH = 8
        RAM_WIDTH = 8
        
        # Calculate remaining width for the final padding
        remaining_width = width - (ID_WIDTH + NAME_WIDTH + IMAGE_WIDTH + PORT_WIDTH + STATUS_WIDTH + UPTIME_WIDTH + RAM_WIDTH) - 10

        header = f"{'ID':<{ID_WIDTH}} {'NAME':<{NAME_WIDTH}} {'IMAGE':<{IMAGE_WIDTH}} {'PORT':<{PORT_WIDTH}} {'STATUS':<{STATUS_WIDTH}} {'UPTIME':<{UPTIME_WIDTH}} {'RAM':<{RAM_WIDTH}}{' ' * remaining_width}"
        list_win.addstr(2, 2, header, curses.A_UNDERLINE)

        list_height = height - 12
        
        if self.selected_index < self.scroll_pos:
            self.scroll_pos = self.selected_index
        if self.selected_index >= self.scroll_pos + list_height:
            self.scroll_pos = self.selected_index - list_height + 1
            
        visible_containers = containers[self.scroll_pos : self.scroll_pos + list_height]

        for i, container in enumerate(visible_containers):
            y_pos = 3 + i
            is_selected = (self.scroll_pos + i) == self.selected_index
            
            ports_text = container['ports']
            status_text = f"{container['status']}"
            uptime_text = f"{container['uptime']}"
            ram_text = f"{container['ram']}"
            status_lower = container['status'].lower()

            # Construct the line with fixed-width columns
            line_part1 = f"{container['id']:<{ID_WIDTH}} {container['name']:<{NAME_WIDTH}.{NAME_WIDTH}} {container['image']:<{IMAGE_WIDTH}.{IMAGE_WIDTH}} {ports_text:<{PORT_WIDTH}.{PORT_WIDTH}} "
            status_str = f"{status_text:<{STATUS_WIDTH-1}} "
            uptime_str = f"{uptime_text:<{UPTIME_WIDTH}}"
            ram_str = f"{ram_text:<{RAM_WIDTH}}"

            line_end = " " * (width - len(line_part1) - len(status_str) - len(uptime_str) - len(ram_str) - 3)
            full_line = f"{line_part1}{status_str}{uptime_str}{ram_str}{line_end}"

            if is_selected:
                base_attr = curses.color_pair(5)
                if 'up' in status_lower:
                    status_attr = curses.color_pair(6)
                elif 'exited' in status_lower:
                    status_attr = curses.color_pair(7)
                else:
                    status_attr = curses.color_pair(8)
            else:
                base_attr = curses.A_NORMAL
                if 'up' in status_lower:
                    status_attr = curses.color_pair(1)
                elif 'exited' in status_lower:
                    status_attr = curses.color_pair(2)
                else:
                    status_attr = curses.color_pair(3)
            
            try:
                # Print the first part of the line (ID, NAME, IMAGE, PORT)
                list_win.addstr(y_pos, 2, line_part1, base_attr)

                # Print the STATUS column
                current_x = 2 + len(line_part1)
                list_win.addstr(y_pos, current_x, status_str.strip(), status_attr)
                
                # Print UPTIME
                current_x += STATUS_WIDTH
                list_win.addstr(y_pos, current_x, uptime_str.strip(), curses.color_pair(1))

                # Print RAM
                current_x += UPTIME_WIDTH + 1
                list_win.addstr(y_pos, current_x, ram_str.strip(), base_attr)

                # Fill the rest of the line with padding
                end_x = 2 + len(line_part1) + STATUS_WIDTH + UPTIME_WIDTH + RAM_WIDTH + 4
                list_win.addstr(y_pos, end_x, " " * (width - end_x -1), base_attr)

            except curses.error:
                pass

        list_win.refresh()

    def _draw_footer(self, stdscr, height: int, width: int):
        """Draws the bottom footer with instructions and status messages."""
        keys = "↑/↓: Nav | U: Update | S: Start | X: Stop | R: Restart | N: Rename | D: Delete | Q: Quit"
        stdscr.addstr(height - 1, 1, keys)
        
        if self.status_message:
            # Check for the temporary status message and apply red color
            if "Stopping container" in self.status_message:
                attr = curses.color_pair(2) | curses.A_BOLD
            else:
                attr = curses.color_pair(3)
            
            stdscr.attron(attr)
            stdscr.addstr(height - 2, 1, f"Status: {self.status_message.ljust(width-10)}")
            stdscr.attroff(attr)
            
            if "Successfully" in self.status_message or "Error" in self.status_message:
                self.status_message = ""


    # --- Main Loop ---

    def _app_loop(self, stdscr):
        """The main application loop that handles drawing and input."""
        curses.curs_set(0)
        stdscr.nodelay(1)
        stdscr.timeout(1000)
        
        self._setup_colors()
        containers = self.get_docker_containers()

        while True:
            height, width = stdscr.getmaxyx()
            
            key = stdscr.getch()

            if key in [ord('q'), ord('Q')]:
                break
            elif key == curses.KEY_UP:
                self.selected_index = max(0, self.selected_index - 1)
            elif key == curses.KEY_DOWN and containers:
                self.selected_index = min(len(containers) - 1, self.selected_index + 1)
            elif key in [ord('u'), ord('U')]:
                containers = self.get_docker_containers()
                self.status_message = "Container list updated."
            elif key in [ord('s'), ord('S')]:
                self._perform_action('start', containers)
            elif key in [ord('x'), ord('X')] and containers:
                self.status_message = "Stopping container, this may take a minute..."
                self._draw_footer(stdscr, height, width)
                stdscr.refresh()
                self._perform_action('stop', containers)
            elif key in [ord('r'), ord('R')]:
                self._perform_action('restart', containers)
            elif key in [ord('d'), ord('D')] and containers:
                container_to_delete = containers[self.selected_index]['name']
                if self._confirm_action(stdscr, f"Delete container '{container_to_delete}'?"):
                    self._perform_action('remove', containers)
            elif key in [ord('n'), ord('N')] and containers:
                current_name = containers[self.selected_index]['name']
                new_name = self._get_new_name(stdscr, current_name)
                if new_name:
                    self._perform_action('rename', containers, new_name)
            
            if key == -1:
                containers = self.get_docker_containers()

            self._draw_header(stdscr, width)
            self._draw_system_stats(stdscr, width)
            self._draw_container_list(stdscr, height, width, containers)
            self._draw_footer(stdscr, height, width)
            stdscr.refresh()
            time.sleep(0.1)

    def run(self):
        """Starts the curses application."""
        try:
            curses.wrapper(self._app_loop)
        except KeyboardInterrupt:
            pass
        finally:
            print("Monitoring stopped.")

def main():
    monitor = SystemMonitor()
    monitor.run()

if __name__ == "__main__":
    main()
