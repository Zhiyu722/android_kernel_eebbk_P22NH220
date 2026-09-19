/* Tiny aarch64 helper for the EEBBK S6 camera elevator.
 *
 * /dev/bbk_hall_core is a misc device with mode 0666.  Its ioctls copy a
 * calibration blob from userspace and push cali_time into the elevator driver
 * (set_vib_all_time -> mhall_control7 = all_time, the full-travel time):
 *
 *   BBK_HALL_CORE_IOCTL_SET_CALI   0x40046000  also persists to
 *                                              /mnt/vendor/persist/sensors/cali_hall
 *   BBK_HALL_CORE_IOCTL_TRANS_CALI 0x40046001  in-memory only (reverted by reboot)
 *
 * struct hall_cali_data is 56 bytes with int cali_time at +0x34.
 *
 * usage: elev trans <cali_time>   temporary
 *        elev set   <cali_time>   persistent
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <errno.h>

#define HALL_CALI_SIZE 56
#define CALI_TIME_OFF  0x34
#define IOCTL_SET_CALI   0x40046000u
#define IOCTL_TRANS_CALI 0x40046001u

int main(int argc, char **argv)
{
	int fd, cali;
	unsigned int cmd;
	unsigned char blob[HALL_CALI_SIZE];

	if (argc < 3) {
		fprintf(stderr, "usage: %s trans|set <cali_time>\n", argv[0]);
		return 2;
	}
	cali = atoi(argv[2]);
	if (cali < 100 || cali > 20000) {
		fprintf(stderr, "cali_time %d out of range (100..20000)\n", cali);
		return 2;
	}
	if (!strcmp(argv[1], "set"))
		cmd = IOCTL_SET_CALI;
	else if (!strcmp(argv[1], "trans"))
		cmd = IOCTL_TRANS_CALI;
	else {
		fprintf(stderr, "unknown mode %s\n", argv[1]);
		return 2;
	}

	fd = open("/dev/bbk_hall_core", O_RDWR);
	if (fd < 0) {
		perror("open /dev/bbk_hall_core");
		return 1;
	}
	memset(blob, 0, sizeof(blob));
	memcpy(blob + CALI_TIME_OFF, &cali, sizeof(cali));

	int r = ioctl(fd, cmd, blob);
	printf("%s: ioctl(0x%08x, cali_time=%d) -> %d (errno %d)\n",
	       argv[1], cmd, cali, r, errno);
	close(fd);
	return r ? 1 : 0;
}
