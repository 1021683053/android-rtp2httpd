/* Android process entry for the GPL-2.0 rtp2httpd core. */
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <unistd.h>

int rtp2httpd_upstream_main(int argc, char *argv[]);

int main(int argc, char *argv[]) {
  const char *parent_text = getenv("RTP2HTTPD_PARENT_PID");
  char *end;
  long parent;
  if (parent_text == NULL || parent_text[0] == '\0') {
    fputs("RTP2HTTPD_PARENT_PID is required; launch through RelayService\n", stderr);
    return 1;
  }
  errno = 0;
  parent = strtol(parent_text, &end, 10);
  if (errno != 0 || *end != '\0' || parent <= 1 || parent > 2147483647L) {
    fputs("Invalid RTP2HTTPD_PARENT_PID\n", stderr);
    return 1;
  }
  /* Workers already arm their own parent-death signal in upstream supervisor.c.
   * Also tie the supervisor to Java, checking the exec/prctl race explicitly. */
  if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0) {
    perror("prctl(PR_SET_PDEATHSIG)");
    return 1;
  }
  if (getppid() != (pid_t)parent) return 1;
  return rtp2httpd_upstream_main(argc, argv);
}
