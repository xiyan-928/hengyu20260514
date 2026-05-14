#ifndef WRAPPER_H
#define WRAPPER_H

#include <stdio.h>

#define TIMEOUT 2000 // milliseconds

#ifdef __cplusplus //如果是c++代码 {}内按照C来编译，不是就正常编译
extern "C" {
#endif

/*****************************
 * 描述: 初始化光谱仪，获取已连接光谱仪数量
 * 参数：int commType: 通讯类型，分别如下：
 *       -1： 错误
 *        0： 启用usb通讯
 *        1： 启动RS232串口通信
 * 返回： 
 *      >0： 可读取到光谱仪数量
 *      <0： 参见Ret返回值错误码枚举列表   
 */
int Init(int commType);


/*****************************
 * 描述: 以初始化的通讯方式，打开指定索引的光谱仪
 * 参数：int index: 光谱仪索引
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int Open(int index);

/*****************************
 * 描述: 获取指定索引光谱仪的序列号
 * 参数：
 *      int index: 光谱仪索引
 *      char *serialNumber： 用于存储序列号的字符串指针，长度 >=8 
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int GetDetectorNumber(int index, char *detectorNumber);


/*****************************
 * 描述: 获取指定索引光谱仪的序列号
 * 参数：
 *      int index: 光谱仪索引
 *      char *serialNumber： 用于存储序列号的字符串指针，长度 >=8 
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int GetSerialNumber(int index, char *serialNumber);


/*****************************
 * 描述: 设置光谱仪积分时间
 * 参数：
 *      int index: 光谱仪索引
 *      int integrationTimeMs： 要设置的光谱仪积分时间，单位是ms 
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int SetIntegrationTime(int index, double integrationTimeMs);


/*****************************
 * 描述: 设置光谱仪平均次数
 * 参数：
 *      int index: 光谱仪索引
 *      int averageTime: 要设置的光谱仪平均次数
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int SetAverageTime(int index, int averageTime);

/*****************************
 * 描述: 获取波长值数量，默认是2048个波长
 * 参数：
 *      int index: 光谱仪索引
 *      int *number: 波长值数量指针，用于在函数中获取波长值数量
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int GetWavelengthsNumber(int index, int *number);

/*****************************
 * 描述: 获取波长值
 * 参数：
 *      int index: 光谱仪索引
 *      float wls: 波长数据指针
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int GetWavelengths(int index, float *wls);

/*****************************
 * 描述: 获取光谱强度值
 * 参数：
 *      int index: 光谱仪索引
 *      uint *scopes: 波长数据指针
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int GetScopes(int index, unsigned short *scopes);


/*****************************
 * 描述: 从设备读取字节序列
 * 参数：
 *      int index: 光谱仪索引
 *      void *buf： 用于接收字节序列的指针
 *      int size： 指定接收的字节长度
 *  
 * 返回：
 *      =0: 返回成功
 *      <0：参见Ret返回值错误码枚举列表
 */
int ReadBytes(int index, void *buf, int size);

#ifdef __cplusplus
}
#endif

#endif // WRAPPER_H