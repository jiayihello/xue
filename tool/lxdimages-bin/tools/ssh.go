package tools

import (
	"fmt"
	"os/exec"
	"time"
)

type SSHConfig struct {
	InstallCommands []string
	ConfigCommands  []string
	EnableCommands  []string
	CleanupCommands []string
}

func GetSSHConfig(distro string) SSHConfig {
	config := SSHConfig{}

	switch distro {
	case "ubuntu", "debian":
		config.InstallCommands = []string{
			"apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server sudo",
		}
	case "centos":
		config.InstallCommands = []string{
			"if command -v dnf >/dev/null 2>&1; then dnf install -y openssh-server sudo; else yum install -y openssh-server sudo; fi",
		}
	case "fedora", "rhel", "almalinux", "rockylinux", "oraclelinux":
		config.InstallCommands = []string{
			"dnf install -y openssh-server sudo",
		}
	case "alpine":
		config.InstallCommands = []string{
			"apk update -q && apk add -q openssh-server sudo bash",
		}
	case "opensuse":
		config.InstallCommands = []string{
			"zypper refresh -q && zypper install -y openssh-server sudo",
		}
	case "amazonlinux":
		config.InstallCommands = []string{
			"yum update -y -q && yum install -y openssh-server sudo",
		}
	default:
		config.InstallCommands = []string{
			"if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server sudo; elif command -v dnf >/dev/null 2>&1; then dnf install -y openssh-server sudo; elif command -v yum >/dev/null 2>&1; then yum install -y openssh-server sudo; elif command -v apk >/dev/null 2>&1; then apk update -q && apk add -q openssh-server sudo bash; fi",
		}
	}

	baseConfigCommands := []string{
		"mkdir -p /run/sshd /var/run/sshd",
		"mkdir -p /root/.ssh && chmod 700 /root/.ssh",
		"echo 'root:password' | chpasswd",
	}

	var sshConfigCommands []string
	switch distro {
	case "alpine":
		sshConfigCommands = []string{
			"cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak",
			`cat > /etc/ssh/sshd_config << 'EOF'
Port 22
PermitRootLogin yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PasswordAuthentication yes
UsePAM no
AllowTcpForwarding yes
X11Forwarding no
Subsystem sftp internal-sftp
EOF`,
		}
		baseConfigCommands = append(baseConfigCommands, "echo 'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' >> /root/.bashrc")
	case "amazonlinux":
		sshConfigCommands = []string{
			"sed -i 's/#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
			"sed -i 's/#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config",
			"sed -i 's/#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config",
			"sed -i 's/#*Port.*/Port 22/' /etc/ssh/sshd_config",
			"sed -i 's/#*UsePAM.*/UsePAM yes/' /etc/ssh/sshd_config",
			"sed -i '/GatewayPort/d' /etc/ssh/sshd_config",
			"sed -i '/GatewayPorts/d' /etc/ssh/sshd_config",
		}
	default:
		sshConfigCommands = []string{
			"sed -i 's/#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
			"sed -i 's/#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config",
			"sed -i 's/#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config",
			"sed -i 's/#*Port.*/Port 22/' /etc/ssh/sshd_config",
			"sed -i 's/#*UsePAM.*/UsePAM yes/' /etc/ssh/sshd_config",
			"sed -i '/GatewayPort[^s]/d' /etc/ssh/sshd_config",
		}
	}
	config.ConfigCommands = append(baseConfigCommands, sshConfigCommands...)

	switch distro {
	case "alpine":
		config.EnableCommands = []string{
			"ssh-keygen -A",
			"sshd -t",
			"rc-update add sshd default",
			"rc-service sshd start",
		}
	case "amazonlinux", "centos", "fedora", "rhel", "almalinux", "rockylinux", "oraclelinux":
		config.EnableCommands = []string{
			"ssh-keygen -A",
			"sshd -t",
			"systemctl enable sshd",
			"systemctl start sshd",
		}
	default:
		config.EnableCommands = []string{
			"ssh-keygen -A",
			"sshd -t",
			"systemctl enable ssh || systemctl enable sshd",
			"systemctl start ssh || systemctl start sshd",
		}
	}

	baseCleanupCommands := []string{
		"history -c",
		"rm -f /root/.bash_history",
		"rm -rf /tmp/* /var/tmp/*",
	}

	if distro == "alpine" {
		baseCleanupCommands = append(baseCleanupCommands,
			"rc-service sshd stop",
			"killall sshd 2>/dev/null || true",
			"pkill -f sshd 2>/dev/null || true",
		)
	}

	switch distro {
	case "ubuntu", "debian":
		baseCleanupCommands = append(baseCleanupCommands, "apt-get clean", "rm -rf /var/lib/apt/lists/*")
	case "centos", "fedora", "rhel", "almalinux", "rockylinux", "oraclelinux":
		baseCleanupCommands = append(baseCleanupCommands, "if command -v dnf >/dev/null 2>&1; then dnf clean all; else yum clean all; fi")
	case "alpine":
		baseCleanupCommands = append(baseCleanupCommands, "rm -rf /var/cache/apk/*")
	case "opensuse":
		baseCleanupCommands = append(baseCleanupCommands, "zypper clean -a")
	case "amazonlinux":
		baseCleanupCommands = append(baseCleanupCommands, "yum clean all")
	}
	config.CleanupCommands = baseCleanupCommands

	return config
}

func ConfigureSSH(containerName, distro string) error {
	fmt.Printf("     安装SSH服务...")
	
	time.Sleep(3 * time.Second)

	config := GetSSHConfig(distro)

	for _, cmdStr := range config.InstallCommands {
		cmd := exec.Command("lxc", "exec", containerName, "--", "sh", "-c", cmdStr)
		cmd.Stdout = nil
		cmd.Stderr = nil
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("安装SSH服务失败: %v", err)
		}
	}
	fmt.Printf(" OK\n")

	fmt.Printf("     配置SSH服务...")
	for _, cmdStr := range config.ConfigCommands {
		cmd := exec.Command("lxc", "exec", containerName, "--", "sh", "-c", cmdStr)
		cmd.Stdout = nil
		cmd.Stderr = nil
		cmd.Run()
	}
	fmt.Printf(" OK\n")

	fmt.Printf("     启用SSH服务...")
	for _, cmdStr := range config.EnableCommands {
		cmd := exec.Command("lxc", "exec", containerName, "--", "sh", "-c", cmdStr)
		cmd.Stdout = nil
		cmd.Stderr = nil
		cmd.Run()
	}
	fmt.Printf(" OK\n")

	fmt.Printf("     安装基础工具...")
	toolCommands := getBaseToolsCommands(distro)
	for _, cmdStr := range toolCommands {
		cmd := exec.Command("lxc", "exec", containerName, "--", "sh", "-c", cmdStr)
		cmd.Stdout = nil
		cmd.Stderr = nil
		cmd.Run()
	}
	fmt.Printf(" OK\n")
	fmt.Printf("     清理缓存...")
	for _, cmdStr := range config.CleanupCommands {
		cmd := exec.Command("lxc", "exec", containerName, "--", "sh", "-c", cmdStr)
		cmd.Stdout = nil
		cmd.Stderr = nil
		cmd.Run()
	}
	fmt.Printf(" OK\n")

	return nil
}

func getBaseToolsCommands(distro string) []string {
	switch distro {
	case "alpine":
		return []string{"apk add -q curl wget nano procps"}
	case "amazonlinux", "centos", "fedora", "rhel", "almalinux", "rockylinux", "oraclelinux":
		return []string{"if command -v dnf >/dev/null 2>&1; then dnf install -y curl wget nano procps-ng; else yum install -y curl wget nano procps-ng; fi"}
	case "ubuntu", "debian":
		return []string{"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl wget nano procps"}
	case "opensuse":
		return []string{"zypper install -y curl wget nano procps"}
	default:
		return []string{"if command -v apk >/dev/null 2>&1; then apk add -q curl wget nano procps; elif command -v apt-get >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl wget nano procps; elif command -v dnf >/dev/null 2>&1; then dnf install -y curl wget nano procps-ng; elif command -v yum >/dev/null 2>&1; then yum install -y curl wget nano procps-ng; fi"}
	}
}
